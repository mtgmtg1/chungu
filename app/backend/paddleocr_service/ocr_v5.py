#!/usr/bin/env python3
# [Flow: Step 1 (PP-StructureV3 파이프라인 풀 지연 초기화) -> Step 2 (페이지 이미지별 predict)
#       -> Step 3 (numpy → JSON 직렬화 가능 형태 변환 + width/height 주입)
#       -> Step 4 (markdown 추출 + markdown_images base64 인라인)
#       -> Step 5 (doc_preprocessor_res.angle 추출) -> Step 6 (per-page 결과 반환)]
"""PaddleOCR v5 (PP-OCRv5 + PP-StructureV3) 로컬 CPU OCR 엔진.

a1(GPU 없음, Xeon 듀얼 소켓 80코어)에서 동작한다. AI Studio API 경로와 **동일한 per-page 결과**
(`markdown` / `layout` / `page_angle`)를 반환하므로 상위 파이프라인(`core/paddleocr_client.py`,
`core/pipeline_vision.py`, `core/pdf_annotate_converter.py`)은 백엔드를 구분하지 않는다.

좌표 규약 (가장 중요):
    PP-StructureV3는 bbox를 **입력 이미지 픽셀 좌표(top-left origin, y↓)** 로 반환한다.
    AI Studio에 이미지를 제출했을 때와 동일한 규약이므로, main._extract_layout_from_result를
    그대로 통과시켜 하위 소비자(core/ocr_layout.py, core/pdf_text_layer.py)의 좌표 계산을
    바꾸지 않는다. PDF도 항상 페이지 이미지로 렌더링한 뒤 추론하므로, AI Studio PDF 직접 제출
    경로(PDF user-space, bottom-left origin)와 달리 **단일 좌표 규약**만 존재한다.

문서 방향 보정:
    AI Studio 경로와 동일하게 `use_doc_orientation_classify=True`(90° 단위 대회전 보정) +
    `use_doc_unwarping=False`(왜곡 보정은 역매핑 불가하므로 금지)로 맞춘다. 보정 각도는
    `doc_preprocessor_res.angle`(0/1/2/3)로 반환되어 클라이언트가 주석 PDF의 베이스 이미지를
    같은 각도로 회전시켜 재현한다.
"""
from __future__ import annotations

import base64
import io
import logging
import os
import queue
import re
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ─── 설정 (환경변수) ───

# 텍스트 인식 모델. PP-OCRv5 기본(server/mobile) rec 모델은 한국어를 지원하지 않으므로
# (PaddleOCR discussion #15371) 한국어 문서가 주력인 본 서비스는 다국어 한국어 모델을 기본값으로 쓴다.
V5_REC_MODEL = os.environ.get("PADDLEOCR_V5_REC_MODEL", "korean_PP-OCRv5_mobile_rec")
# 검출 모델. server가 기본값이다 — mobile은 34% 빠르지만 검출 라인이 줄어든다.
# a1 실측(같은 페이지): server 130.1s / 239 라인,  mobile 86.3s / 234 라인 (-2%)
# 법률 문서는 누락이 곧 결함이므로 기본값은 품질 우선(server)으로 두고, 처리량이 급할 때만
# PADDLEOCR_V5_DET_MODEL=PP-OCRv5_mobile_det 로 내린다.
V5_DET_MODEL = os.environ.get("PADDLEOCR_V5_DET_MODEL", "PP-OCRv5_server_det")
# 파이프라인 인스턴스 풀 크기. PaddleOCR 파이프라인은 thread-safe를 보장하지 않으므로
# 인스턴스를 풀로 관리하고 한 인스턴스는 한 스레드만 사용한다.
V5_POOL_SIZE = max(1, int(os.environ.get("PADDLEOCR_V5_POOL_SIZE", "4")))
# 인스턴스당 Paddle inference CPU 스레드 수 (POOL_SIZE × CPU_THREADS ≈ 물리 코어 수)
V5_CPU_THREADS = max(1, int(os.environ.get("PADDLEOCR_V5_CPU_THREADS", "16")))
# oneDNN(MKLDNN) 가속은 paddlepaddle 3.3.1에서 PP-StructureV3 추론 중 죽는다:
#   NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support
#   [pir::ArrayAttribute<pir::DoubleAttribute>] (onednn_instruction.cc)
# a1에서 실측 확인했으므로 기본값은 off다. paddle 업그레이드 후 재시도해볼 만한 성능 레버.
V5_ENABLE_MKLDNN = os.environ.get("PADDLEOCR_V5_ENABLE_MKLDNN", "false").lower() == "true"
V5_ORIENTATION_CLASSIFY = os.environ.get("PADDLEOCR_V5_ORIENTATION_CLASSIFY", "true").lower() == "true"
V5_TABLE_RECOGNITION = os.environ.get("PADDLEOCR_V5_TABLE_RECOGNITION", "true").lower() == "true"
V5_FORMULA_RECOGNITION = os.environ.get("PADDLEOCR_V5_FORMULA_RECOGNITION", "false").lower() == "true"
V5_SEAL_RECOGNITION = os.environ.get("PADDLEOCR_V5_SEAL_RECOGNITION", "true").lower() == "true"
V5_CHART_RECOGNITION = os.environ.get("PADDLEOCR_V5_CHART_RECOGNITION", "false").lower() == "true"
# 표/도장 서브파이프라인의 인식 모델까지 한국어 모델로 교체할지 여부.
# PP-StructureV3 기본 설정에는 TextRecognition이 **세 곳**에 있는데
# (GeneralOCR / TableRecognition.GeneralOCR / SealRecognition.SealOCR),
# `text_recognition_model_name` kwarg는 첫 번째(본문)만 바꾼다. 나머지 둘은
# 한국어를 지원하지 않는 PP-OCRv5_server_rec으로 남아 표 셀과 도장 글자가 깨진다.
# (a1에서 paddleocr 3.7.0 기본 설정을 덤프해 실측 확인)
V5_PATCH_ALL_RECOGNIZERS = (
    os.environ.get("PADDLEOCR_V5_PATCH_ALL_RECOGNIZERS", "true").lower() == "true"
)
# 텍스트 인식 배치 크기. **올리면 오히려 느려진다** — a1 실측(1755x1240 한국어 스캔, 1페이지):
#   batch=1 → 113.4s,  batch=8 → 130.1s (인식 결과는 동일: 표 안 한글 311자)
# 텍스트라인 폭이 제각각이라 배치 패딩 낭비가 배치 이득을 넘어서는 것으로 보인다.
# paddlex 기본값(1)을 그대로 쓴다.
V5_REC_BATCH_SIZE = max(1, int(os.environ.get("PADDLEOCR_V5_REC_BATCH_SIZE", "1")))
# 레이아웃 검출 모델. 빈 값이면 paddlex 기본값(PP-DocLayout_plus-L)을 유지한다.
# [경고] 낮추면 안 된다 — a1 실측에서 PP-DocLayout-S는 한국어 스캔 표 문서의 레이아웃을
# 하나도 검출하지 못했다 (119.5s에 표 0개, 마크다운 한글 0자: OCR 라인은 239개 나왔지만
# 블록이 없어 마크다운/표가 통째로 비었다). 속도 이득(-8%)도 작다.
# 이 값은 다른 문서 유형에서 실측한 뒤에만 건드릴 것.
V5_LAYOUT_MODEL = os.environ.get("PADDLEOCR_V5_LAYOUT_MODEL", "").strip()

# PPStructureV3.predict()가 받는 파라미터 화이트리스트.
# 자동 파라미터 추천기(core/paddleocr_parameter_recommender.py)는 PaddleOCR-VL 전용 키
# (use_ocr_for_image_block / format_block_content 등)도 내보내므로, 여기서 걸러내야
# predict()가 TypeError로 죽지 않는다.
# paddleocr 3.7.0의 PPStructureV3.predict() 실제 시그니처를 a1에서 실측해 맞춘 목록이다.
# 목록에 없는 키를 넘기면 paddlex가 `ValueError: Unknown argument: X`로 거부한다.
# (`use_layout_detection`은 predict()에 존재하지 않고, `format_block_content`는 존재한다 —
#  PaddleOCR-VL 기준으로 짐작하면 틀리므로 버전을 올릴 때 반드시 재확인할 것.)
PREDICT_PARAM_WHITELIST = frozenset({
    "use_doc_orientation_classify",
    "use_doc_unwarping",
    "use_textline_orientation",
    "use_seal_recognition",
    "use_table_recognition",
    "use_formula_recognition",
    "use_chart_recognition",
    "use_region_detection",
    "format_block_content",
    "layout_threshold",
    "layout_nms",
    "layout_unclip_ratio",
    "layout_merge_bboxes_mode",
    "text_det_limit_side_len",
    "text_det_limit_type",
    "text_det_thresh",
    "text_det_box_thresh",
    "text_det_unclip_ratio",
    "text_rec_score_thresh",
})

# 90° 단위 회전 각도 코드 (doc_preprocessor_res.angle) 중 가로/세로가 뒤바뀌는 값
_SWAPPED_ANGLE_CODES = (1, 3)


# ─── 파이프라인 풀 ───

_pool: queue.Queue | None = None
_pool_lock = threading.Lock()
_created = 0


def is_available() -> bool:
    """PP-StructureV3(paddleocr 3.x)를 이 컨테이너에서 쓸 수 있는지 확인한다."""
    try:
        from paddleocr import PPStructureV3  # noqa: F401
    except Exception as e:
        logger.warning(f"[ocr-v5] PPStructureV3 import 실패: {e}")
        return False
    return True


_patched_config_path: str | None = None
_patched_config_failed = False
_config_lock = threading.Lock()


def _find_default_config() -> Path | None:
    """paddlex 패키지에 들어있는 PP-StructureV3 기본 설정 YAML 경로를 찾는다."""
    try:
        import paddlex
    except Exception as e:
        logger.warning(f"[ocr-v5] paddlex import 실패, 설정 패치 생략: {e}")
        return None
    root = Path(paddlex.__file__).parent
    direct = root / "configs" / "pipelines" / "PP-StructureV3.yaml"
    if direct.is_file():
        return direct
    for candidate in root.rglob("PP-StructureV3.yaml"):
        return candidate
    logger.warning("[ocr-v5] PP-StructureV3.yaml 기본 설정을 찾지 못해 설정 패치를 생략한다")
    return None


def _patch_recognizers(node: Any, stats: dict[str, int], path: str = "") -> None:
    """설정 트리를 순회하며 모든 TextRecognition 모듈(및 선택적으로 레이아웃 모델)을 교체한다.

    [Flow: Step 1 (dict/list 재귀 순회) -> Step 2 (TextRecognition 키를 만나면 model_name 교체)
          -> Step 3 (batch_size 지정) -> Step 4 (LayoutDetection 모델 선택적 교체)
          -> Step 5 (교체 횟수 집계)]

    `TextRecognition` 키를 이름으로 찾으므로, paddleocr 버전이 올라가 서브파이프라인이
    추가되어도 새 인식기가 자동으로 함께 교체된다.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            if key == "TextRecognition" and isinstance(value, dict):
                previous = value.get("model_name")
                value["model_name"] = V5_REC_MODEL
                value["batch_size"] = V5_REC_BATCH_SIZE
                stats["patched"] += 1
                if previous != V5_REC_MODEL:
                    logger.info(f"[ocr-v5] 인식 모델 교체: {child_path} {previous} → {V5_REC_MODEL}")
                continue
            if key == "LayoutDetection" and isinstance(value, dict) and V5_LAYOUT_MODEL:
                previous = value.get("model_name")
                value["model_name"] = V5_LAYOUT_MODEL
                stats["layout_patched"] = stats.get("layout_patched", 0) + 1
                if previous != V5_LAYOUT_MODEL:
                    logger.info(f"[ocr-v5] 레이아웃 모델 교체: {child_path} {previous} → {V5_LAYOUT_MODEL}")
                continue
            _patch_recognizers(value, stats, child_path)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _patch_recognizers(value, stats, f"{path}[{index}]")


def _korean_config_path() -> str | None:
    """모든 인식기를 한국어 모델로 교체한 PP-StructureV3 설정 파일 경로를 반환한다.

    [Flow: Step 1 (이미 만들어둔 경로가 있으면 재사용) -> Step 2 (기본 설정 YAML 로드)
          -> Step 3 (모든 TextRecognition 교체) -> Step 4 (임시 파일로 기록)]

    실패하면 None을 반환하고 호출자는 설정 없이(본문만 한국어) 진행한다 — 품질은 떨어지지만
    OCR 자체가 멈추는 것보다 낫다.
    """
    global _patched_config_path, _patched_config_failed
    if _patched_config_path is not None or _patched_config_failed:
        return _patched_config_path
    with _config_lock:
        if _patched_config_path is not None or _patched_config_failed:
            return _patched_config_path
        try:
            import tempfile

            import yaml

            default_path = _find_default_config()
            if default_path is None:
                _patched_config_failed = True
                return None
            config = yaml.safe_load(default_path.read_text(encoding="utf-8"))
            stats = {"patched": 0}
            _patch_recognizers(config, stats)
            if stats["patched"] == 0:
                logger.warning("[ocr-v5] 설정에서 TextRecognition을 찾지 못했다 — 패치 생략")
                _patched_config_failed = True
                return None
            out_dir = Path(tempfile.gettempdir()) / "paddleocr_v5_config"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / "PP-StructureV3.korean.yaml"
            out_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
            logger.info(
                f"[ocr-v5] 한국어 설정 생성 완료: {out_path} "
                f"(인식기 {stats['patched']}개 → {V5_REC_MODEL}, rec_batch_size={V5_REC_BATCH_SIZE})"
            )
            _patched_config_path = str(out_path)
            return _patched_config_path
        except Exception as e:
            logger.warning(f"[ocr-v5] 한국어 설정 생성 실패, 기본 설정으로 진행: {e}")
            _patched_config_failed = True
            return None


def _build_pipeline() -> Any:
    """PP-StructureV3 인스턴스를 생성한다.

    [Flow: Step 1 (전체 kwargs로 생성 시도) -> Step 2 (인자 관련 예외면 kwarg를 줄여 재시도)
          -> Step 3 (최소 kwargs로 최종 시도) -> Step 4 (그 외 예외는 즉시 전파)]

    paddleocr 버전에 따라 생성자 kwargs가 달라지므로 단계적으로 축소하며 재시도한다.
    단, paddlex는 미지원 인자를 `TypeError`가 아니라 `ValueError: Unknown argument: X`로
    거부하므로 두 예외를 모두 잡아야 한다 (a1에서 paddleocr 3.7.0으로 실측).
    의존성 누락처럼 kwarg와 무관한 예외는 축소해도 똑같이 실패하므로 즉시 전파해
    "PP-StructureV3 추가 의존성 미설치" 원인이 로그에 그대로 드러나게 한다.
    """
    from paddleocr import PPStructureV3

    full_kwargs: dict[str, Any] = {
        "device": "cpu",
        "text_recognition_model_name": V5_REC_MODEL,
        "text_detection_model_name": V5_DET_MODEL,
        "enable_mkldnn": V5_ENABLE_MKLDNN,
        "cpu_threads": V5_CPU_THREADS,
        "use_doc_orientation_classify": V5_ORIENTATION_CLASSIFY,
        "use_doc_unwarping": False,
        "use_table_recognition": V5_TABLE_RECOGNITION,
        "use_formula_recognition": V5_FORMULA_RECOGNITION,
        "use_seal_recognition": V5_SEAL_RECOGNITION,
        "use_chart_recognition": V5_CHART_RECOGNITION,
    }
    # 표/도장 서브파이프라인까지 한국어 인식 모델로 맞춘 설정 파일을 함께 넘긴다.
    # kwarg(text_recognition_model_name)는 본문 인식기만 바꾸므로 이 설정이 없으면
    # 표 셀과 도장 글자가 한국어를 지원하지 않는 모델로 인식된다.
    config_path = _korean_config_path() if V5_PATCH_ALL_RECOGNIZERS else None
    if config_path:
        full_kwargs["paddlex_config"] = config_path

    # 축소 순서: 설정 파일 → 성능 튜닝 kwarg → 모델 선택 kwarg → device만
    fallbacks: list[dict[str, Any]] = [
        full_kwargs,
        {k: v for k, v in full_kwargs.items() if k != "paddlex_config"},
        {k: v for k, v in full_kwargs.items() if k not in ("enable_mkldnn", "cpu_threads")},
        {
            "device": "cpu",
            "text_recognition_model_name": V5_REC_MODEL,
            "use_doc_orientation_classify": V5_ORIENTATION_CLASSIFY,
            "use_doc_unwarping": False,
        },
        {"device": "cpu"},
    ]

    last_error: Exception | None = None
    for kwargs in fallbacks:
        try:
            pipeline = PPStructureV3(**kwargs)
            logger.info(f"[ocr-v5] PPStructureV3 초기화 완료 (kwargs={sorted(kwargs)})")
            return pipeline
        except (TypeError, ValueError) as e:
            logger.warning(f"[ocr-v5] PPStructureV3 kwargs 미지원, 축소 재시도: {e}")
            last_error = e
    raise RuntimeError(f"Failed to initialize PPStructureV3: {last_error}")


def reset_pool() -> None:
    """파이프라인 풀을 비운다 (벤치마크에서 pool_size를 바꿔가며 재측정할 때 사용).

    운영 중 호출하면 이미 대여된 인스턴스는 반납 시 새 풀로 들어가지 않고 버려진다.
    """
    global _pool, _created
    with _pool_lock:
        _pool = None
        _created = 0
    logger.info("[ocr-v5] 파이프라인 풀 초기화")


def _get_pool() -> queue.Queue:
    """파이프라인 풀을 반환한다 (최초 호출 시 생성)."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            _pool = queue.Queue(maxsize=V5_POOL_SIZE)
            logger.info(
                f"[ocr-v5] 파이프라인 풀 준비 (pool_size={V5_POOL_SIZE}, "
                f"cpu_threads={V5_CPU_THREADS}, rec={V5_REC_MODEL}, det={V5_DET_MODEL})"
            )
    return _pool


class _Lease:
    """풀에서 파이프라인 하나를 대여하는 컨텍스트 매니저.

    [Flow: Step 1 (풀에서 즉시 꺼내기 시도) -> Step 2 (없고 정원 미달이면 새로 생성)
          -> Step 3 (정원 초과면 반납 대기) -> Step 4 (사용 후 풀에 반납)]
    """

    def __init__(self) -> None:
        self._pipeline: Any = None

    def __enter__(self) -> Any:
        global _created
        pool = _get_pool()
        try:
            self._pipeline = pool.get_nowait()
            return self._pipeline
        except queue.Empty:
            pass
        with _pool_lock:
            can_create = _created < V5_POOL_SIZE
            if can_create:
                _created += 1
        if can_create:
            try:
                self._pipeline = _build_pipeline()
            except Exception:
                with _pool_lock:
                    _created -= 1
                raise
            return self._pipeline
        self._pipeline = pool.get()  # 반납 대기
        return self._pipeline

    def __exit__(self, *_exc: Any) -> None:
        if self._pipeline is not None:
            _get_pool().put(self._pipeline)
            self._pipeline = None


# ─── 결과 변환 ───

def _to_jsonable(obj: Any) -> Any:
    """numpy 배열/스칼라를 포함한 결과 트리를 JSON 직렬화 가능한 형태로 변환한다.

    PP-StructureV3의 `res.json`은 rec_boxes/rec_polys 등을 numpy 배열(int16)로 담고 있어
    FastAPI 응답 직렬화와 하위 소비자의 float() 변환이 모두 실패한다.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(v) for v in obj]
    tolist = getattr(obj, "tolist", None)
    if callable(tolist):
        try:
            return _to_jsonable(tolist())
        except Exception:
            pass
    item = getattr(obj, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


def _raw_json(res: Any) -> dict:
    """결과 객체에서 res.json 딕셔너리를 꺼내 JSON 직렬화 가능한 형태로 반환한다."""
    try:
        raw = getattr(res, "json", None)
        if raw is None:
            return {}
        if isinstance(raw, dict) and "res" in raw and isinstance(raw["res"], dict):
            raw = raw["res"]
        return _to_jsonable(raw) if isinstance(raw, dict) else {}
    except Exception as e:
        logger.warning(f"[ocr-v5] res.json 추출 실패: {e}")
        return {}


def _angle_code(raw: dict) -> int:
    """doc_preprocessor_res.angle(0/1/2/3)을 반환한다. 없으면 -1."""
    doc_pre = raw.get("doc_preprocessor_res") or {}
    if not isinstance(doc_pre, dict):
        return -1
    angle = doc_pre.get("angle", -1)
    if isinstance(angle, bool) or not isinstance(angle, (int, float)):
        return -1
    code = int(angle)
    # 일부 버전은 각도(0/90/180/270)를 그대로 내보낸다 — 코드(0~3)로 정규화한다.
    if code in (90, 180, 270):
        return {90: 1, 180: 2, 270: 3}[code]
    return code if code in (0, 1, 2, 3) else -1


def _image_size(image_path: Path) -> tuple[int, int]:
    """이미지 픽셀 크기 (width, height)를 반환한다."""
    from PIL import Image

    with Image.open(str(image_path)) as img:
        return int(img.width), int(img.height)


def _inject_page_size(raw: dict, image_path: Path, angle_code: int) -> dict:
    """layout dict에 width/height(px)를 주입한다.

    [Flow: Step 1 (res.json에 이미 width/height가 있으면 유지) -> Step 2 (없으면 원본 이미지 크기 사용)
          -> Step 3 (90°/270° 보정이 적용된 페이지는 가로/세로를 교환)]

    main._extract_layout_from_result는 width/height가 없으면 bbox 정규화를 건너뛰고 원본
    좌표를 그대로 반환하므로(하위 소비자가 전부 오작동), 반드시 채워야 한다.
    문서 방향 보정이 90°/270°로 적용되면 bbox는 회전된 이미지 기준이므로 크기도 교환한다.
    """
    width = raw.get("width")
    height = raw.get("height")
    if isinstance(width, (int, float)) and width > 0 and isinstance(height, (int, float)) and height > 0:
        return raw
    try:
        img_w, img_h = _image_size(image_path)
    except Exception as e:
        logger.warning(f"[ocr-v5] {image_path.name} 이미지 크기 확인 실패: {e}")
        return raw
    if angle_code in _SWAPPED_ANGLE_CODES:
        img_w, img_h = img_h, img_w
    raw["width"] = img_w
    raw["height"] = img_h
    return raw


def _markdown_text(res: Any) -> str:
    """결과 객체에서 마크다운 본문을 추출하고 이미지를 base64 data URI로 인라인한다.

    [Flow: Step 1 (res.markdown dict에서 markdown_texts 추출) -> Step 2 (markdown_images의
          PIL 이미지를 base64 data URI로 변환) -> Step 3 (src 속성 치환) -> Step 4 (div 래퍼 제거)]

    AI Studio 경로(_aistudio_download_and_parse)와 동일하게 이미지를 마크다운에 직접
    인라인해서, 컨테이너 내부 경로 의존성 없이 프론트엔드가 바로 렌더링할 수 있게 한다.
    """
    md_info = getattr(res, "markdown", None)
    if md_info is None:
        return ""

    if isinstance(md_info, dict):
        text = md_info.get("markdown_texts") or md_info.get("markdown") or ""
        images = md_info.get("markdown_images") or {}
    else:
        text = getattr(md_info, "markdown_texts", None) or getattr(md_info, "markdown", None) or ""
        images = getattr(md_info, "markdown_images", None) or {}

    if not isinstance(text, str):
        text = str(text) if text else ""
    if not text:
        return ""

    if isinstance(images, dict):
        for rel_path, image in images.items():
            data_uri = _image_to_data_uri(image)
            if not data_uri:
                continue
            text = text.replace(f'src="{rel_path}"', f'src="{data_uri}"')
            text = text.replace(f"src='{rel_path}'", f"src='{data_uri}'")

    # div 래퍼 제거 (ProseMirror 호환성) — AI Studio 경로와 동일 처리
    return re.sub(r"<div[^>]*>(<img[^>]*>)</div>", r"\1", text)


def _image_to_data_uri(image: Any) -> str:
    """PIL 이미지를 PNG base64 data URI로 변환한다. 실패 시 빈 문자열."""
    try:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception as e:
        logger.warning(f"[ocr-v5] 마크다운 이미지 인라인 실패: {e}")
        return ""


def _filtered_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """predict()가 지원하는 파라미터만 남기고, 좌표 정합에 해로운 값은 강제 고정한다."""
    filtered: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in (params or {}).items():
        if key in PREDICT_PARAM_WHITELIST:
            filtered[key] = value
        else:
            dropped.append(key)
    if dropped:
        logger.debug(f"[ocr-v5] PP-StructureV3 미지원 파라미터 제외: {sorted(dropped)}")
    # 왜곡 보정(unwarping)은 변환 행렬을 노출하지 않아 bbox 역매핑이 불가능하다 — 항상 끈다.
    filtered["use_doc_unwarping"] = False
    filtered.setdefault("use_doc_orientation_classify", V5_ORIENTATION_CLASSIFY)
    return filtered


# ─── 공개 API ───

def predict_page(
    image_path: Path,
    params: dict[str, Any] | None = None,
    layout_extractor: Any = None,
) -> dict[str, Any]:
    """페이지 이미지 한 장을 OCR하여 {markdown, layout, page_angle}을 반환한다.

    [Flow: Step 1 (풀에서 파이프라인 대여) -> Step 2 (predict 실행)
          -> Step 3 (res.json → JSON 변환 + width/height 주입) -> Step 4 (layout 정규화)
          -> Step 5 (markdown 추출)]

    Args:
        image_path: 페이지 이미지 경로 (PNG/JPG 등).
        params: 자동 추천 파라미터. PP-StructureV3 미지원 키는 자동으로 제외된다.
        layout_extractor: bbox 정규화 함수 (main._extract_layout_from_result).
            None이면 정규화 없이 원본 좌표 dict를 반환한다.

    Returns:
        {"markdown": str, "layout": dict, "page_angle": int}
    """
    predict_params = _filtered_params(params)
    with _Lease() as pipeline:
        output = pipeline.predict(str(image_path), **predict_params)
        results = list(output)

    if not results:
        logger.warning(f"[ocr-v5] {image_path.name} 결과 없음")
        return {"markdown": "", "layout": {}, "page_angle": -1}

    res = results[0]
    raw = _raw_json(res)
    angle = _angle_code(raw)
    raw = _inject_page_size(raw, image_path, angle)
    layout = layout_extractor(raw) if layout_extractor is not None else raw
    return {
        "markdown": _markdown_text(res),
        "layout": layout if isinstance(layout, dict) else {},
        "page_angle": angle,
    }


def predict_pages(
    image_paths: list[Path],
    params: dict[str, Any] | None = None,
    layout_extractor: Any = None,
    max_workers: int | None = None,
    on_page_done: Any = None,
) -> list[dict[str, Any]]:
    """여러 페이지 이미지를 병렬 OCR하여 입력 순서대로 per-page 결과를 반환한다.

    [Flow: Step 1 (워커 수 결정) -> Step 2 (ThreadPoolExecutor로 페이지별 predict 제출)
          -> Step 3 (실패 페이지는 빈 결과로 채움) -> Step 4 (입력 순서로 정렬해 반환)]

    실패한 페이지는 예외를 던지지 않고 빈 결과로 채운다 — 100페이지 중 한 장 실패가
    전체 작업을 되돌리지 않게 하기 위함이다(AI Studio 경로의 per-page 폴백과 동일한 정책).
    """
    if not image_paths:
        return []

    from concurrent.futures import ThreadPoolExecutor

    workers = max_workers if max_workers is not None else min(V5_POOL_SIZE, len(image_paths))
    workers = max(1, workers)
    results: list[dict[str, Any]] = [
        {"markdown": "", "layout": {}, "page_angle": -1} for _ in image_paths
    ]

    def _run(idx: int, path: Path) -> None:
        try:
            results[idx] = predict_page(path, params, layout_extractor)
        except Exception as e:
            logger.error(f"[ocr-v5] 페이지 {idx + 1} 추론 실패: {e}")
            results[idx] = {
                "markdown": f"<!-- Page {idx + 1} (OCR 실패) -->\n",
                "layout": {},
                "page_angle": -1,
            }
        finally:
            if on_page_done is not None:
                try:
                    on_page_done(idx)
                except Exception:
                    pass

    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(lambda a: _run(*a), list(enumerate(image_paths))))

    return results
