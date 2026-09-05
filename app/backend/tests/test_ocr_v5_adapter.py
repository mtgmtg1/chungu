#!/usr/bin/env python3
# [Flow: Step 1 (numpy 유사 객체 직렬화 검증) -> Step 2 (회전 각도/페이지 크기 주입 검증)
#       -> Step 3 (마크다운 추출 및 이미지 인라인 검증) -> Step 4 (파라미터 화이트리스트 검증)
#       -> Step 5 (predict_page/predict_pages 통합 및 좌표 정규화 검증)]
"""로컬 PaddleOCR v5(PP-OCRv5 + PP-StructureV3) 어댑터 단위 테스트.

PP-StructureV3 실제 추론은 GPU/모델 없이 돌릴 수 없으므로, 파이프라인을 가짜 객체로
대체하고 **AI Studio 경로와 동일한 per-page 결과를 만들어내는지**를 검증한다.
특히 좌표 규약(정규화 결과가 하위 소비자 기대와 일치하는지)이 회귀 방지 대상이다.
"""
import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.paddleocr_service import ocr_v5
import functools

from backend.paddleocr_service.main import _extract_layout_from_result

# PP-StructureV3 는 bbox 를 top-left 이미지 픽셀 좌표로 반환하므로, 프로덕션의
# _v5_predict 와 동일하게 flip_y=False 로 고정한 추출기를 쓴다. 기본값(True)은
# AI Studio 가 PDF 를 직접 받았을 때(bottom-left)를 위한 것이다.
_v5_layout_extractor = functools.partial(_extract_layout_from_result, flip_y=False)


# ─── 테스트 더블 ───

class _FakeArray:
    """numpy 배열처럼 tolist()를 제공하는 더블."""

    def __init__(self, value):
        self._value = value

    def tolist(self):
        return self._value


class _FakeScalar:
    """numpy 스칼라처럼 item()을 제공하는 더블."""

    def __init__(self, value):
        self._value = value

    def item(self):
        return self._value


class _FakeImage:
    """PIL.Image처럼 save(buf, format=...)를 제공하는 더블."""

    def __init__(self, payload: bytes = b"\x89PNG-fake"):
        self._payload = payload

    def save(self, fp, format=None):  # noqa: A002 - PIL 시그니처 호환
        fp.write(self._payload)


class _FakeRes:
    """PP-StructureV3 결과 객체 더블 (res.json / res.markdown)."""

    def __init__(self, raw: dict, markdown: dict | None = None):
        self.json = raw
        self.markdown = markdown if markdown is not None else {"markdown_texts": ""}


class _FakePipeline:
    """predict()가 미리 정해둔 결과를 돌려주는 파이프라인 더블."""

    def __init__(self, results_by_call: list, record: list | None = None):
        self._results = list(results_by_call)
        self._record = record

    def predict(self, path, **kwargs):
        if self._record is not None:
            self._record.append((path, kwargs))
        if not self._results:
            return []
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return [item]


@pytest.fixture
def fake_lease(monkeypatch):
    """ocr_v5._Lease를 가짜 파이프라인으로 대체하는 팩토리를 돌려준다."""

    def _install(results, record=None):
        pipeline = _FakePipeline(results, record)

        class _Lease:
            def __enter__(self):
                return pipeline

            def __exit__(self, *_exc):
                return None

        monkeypatch.setattr(ocr_v5, "_Lease", _Lease)
        return pipeline

    return _install


def _png(tmp_path: Path, name: str, size: tuple[int, int]) -> Path:
    """지정한 픽셀 크기의 실제 PNG 파일을 만들어 경로를 반환한다."""
    from PIL import Image

    path = tmp_path / name
    Image.new("RGB", size, "white").save(path, "PNG")
    return path


# ─── _to_jsonable ───

def test_to_jsonable_converts_numpy_like_structures():
    """[Flow: Step 1 (배열/스칼라 더블을 중첩) -> Step 2 (_to_jsonable 호출)
          -> Step 3 (순수 파이썬 타입만 남는지 검증)]

    PP-StructureV3의 res.json은 rec_boxes를 numpy int16 배열로 담고 있어, 변환 없이는
    FastAPI 직렬화와 하위 소비자의 float() 변환이 모두 실패한다.
    """
    raw = {
        "rec_boxes": _FakeArray([[1, 2, 3, 4]]),
        "score": _FakeScalar(0.5),
        "nested": {"points": [_FakeArray([1, 2]), (3, 4)]},
        "path": Path("/tmp/x.png"),
    }
    out = ocr_v5._to_jsonable(raw)
    assert out["rec_boxes"] == [[1, 2, 3, 4]]
    assert out["score"] == 0.5
    assert out["nested"]["points"] == [[1, 2], [3, 4]]
    assert out["path"] == "/tmp/x.png"


def test_raw_json_unwraps_res_key():
    """res.json이 {"res": {...}} 로 감싸져 오는 버전도 벗겨내야 한다."""
    res = _FakeRes({"res": {"width": 10, "height": 20}})
    assert ocr_v5._raw_json(res) == {"width": 10, "height": 20}


# ─── 회전 각도 ───

@pytest.mark.parametrize(
    "angle_value,expected",
    [(0, 0), (1, 1), (2, 2), (3, 3), (90, 1), (180, 2), (270, 3), (None, -1), ("x", -1), (7, -1)],
)
def test_angle_code_normalizes_codes_and_degrees(angle_value, expected):
    """doc_preprocessor_res.angle이 코드(0~3)든 각도(90/180/270)든 코드로 정규화한다."""
    raw = {"doc_preprocessor_res": {"angle": angle_value}} if angle_value is not None else {}
    assert ocr_v5._angle_code(raw) == expected


def test_angle_code_missing_doc_preprocessor():
    assert ocr_v5._angle_code({}) == -1
    assert ocr_v5._angle_code({"doc_preprocessor_res": None}) == -1


# ─── 페이지 크기 주입 ───

def test_inject_page_size_uses_image_dimensions(tmp_path):
    """[Flow: Step 1 (width/height 없는 layout) -> Step 2 (_inject_page_size)
          -> Step 3 (이미지 실제 픽셀 크기가 채워지는지 검증)]

    width/height가 없으면 _extract_layout_from_result가 bbox 정규화를 건너뛰고 원본 좌표를
    그대로 반환해 하위 소비자가 전부 오작동한다.
    """
    img = _png(tmp_path, "p.png", (300, 500))
    out = ocr_v5._inject_page_size({}, img, angle_code=0)
    assert out["width"] == 300
    assert out["height"] == 500


def test_inject_page_size_swaps_for_quarter_turns(tmp_path):
    """90°/270° 보정이 적용된 페이지는 bbox가 회전된 이미지 기준이므로 가로/세로를 교환한다."""
    img = _png(tmp_path, "p.png", (300, 500))
    for angle in (1, 3):
        out = ocr_v5._inject_page_size({}, img, angle_code=angle)
        assert (out["width"], out["height"]) == (500, 300), f"angle={angle}"


def test_inject_page_size_keeps_existing_values(tmp_path):
    """결과에 이미 width/height가 있으면 이미지 크기로 덮어쓰지 않는다."""
    img = _png(tmp_path, "p.png", (300, 500))
    out = ocr_v5._inject_page_size({"width": 11, "height": 22}, img, angle_code=0)
    assert (out["width"], out["height"]) == (11, 22)


# ─── 마크다운 ───

def test_markdown_text_inlines_images_as_data_uri():
    """[Flow: Step 1 (markdown_texts + markdown_images) -> Step 2 (_markdown_text)
          -> Step 3 (src가 base64 data URI로 치환되고 div 래퍼가 제거되는지 검증)]

    AI Studio 경로와 동일하게 이미지를 인라인해야 컨테이너 내부 경로 의존성 없이
    프론트엔드가 바로 렌더링할 수 있다.
    """
    res = _FakeRes(
        {},
        {
            "markdown_texts": '<div class="x"><img src="imgs/0.png"/></div>\n본문',
            "markdown_images": {"imgs/0.png": _FakeImage()},
        },
    )
    out = ocr_v5._markdown_text(res)
    assert "data:image/png;base64," in out
    assert 'src="imgs/0.png"' not in out
    assert "<div" not in out
    assert "본문" in out


def test_markdown_text_handles_missing_and_empty():
    assert ocr_v5._markdown_text(_FakeRes({}, {"markdown_texts": ""})) == ""
    assert ocr_v5._markdown_text(_FakeRes({}, {})) == ""


def test_markdown_text_survives_unsaveable_image():
    """이미지 인라인이 실패해도 본문 마크다운은 보존한다."""

    class _Broken:
        def save(self, *_a, **_k):
            raise RuntimeError("boom")

    res = _FakeRes({}, {"markdown_texts": '<img src="a.png"/>본문', "markdown_images": {"a.png": _Broken()}})
    out = ocr_v5._markdown_text(res)
    assert "본문" in out
    assert 'src="a.png"' in out


# ─── 파라미터 화이트리스트 ───

def test_filtered_params_drops_unsupported_keys_and_forces_unwarping_off():
    """[Flow: Step 1 (미지원 키가 섞인 추천 파라미터) -> Step 2 (_filtered_params)
          -> Step 3 (지원 키만 남고 unwarping이 강제 off인지 검증)]

    자동 파라미터 추천기는 PaddleOCR-VL 전용 키도 내보낸다. 걸러내지 않으면 paddlex가
    `ValueError: Unknown argument: X`로 추론 자체를 거부한다.
    화이트리스트는 a1에서 실측한 paddleocr 3.7.0의 predict() 시그니처 기준이다 —
    `use_ocr_for_image_block`/`use_layout_detection`은 없고 `format_block_content`는 있다.
    """
    params = {
        "layout_threshold": 0.4,
        "use_doc_unwarping": True,          # 강제 off 되어야 함
        "format_block_content": True,       # PP-StructureV3가 지원 → 유지
        "use_ocr_for_image_block": True,    # VL 전용 → 제거
        "use_layout_detection": True,       # predict()에 없음 → 제거
    }
    out = ocr_v5._filtered_params(params)
    assert out["layout_threshold"] == 0.4
    assert out["use_doc_unwarping"] is False
    assert out["format_block_content"] is True
    assert "use_ocr_for_image_block" not in out
    assert "use_layout_detection" not in out
    assert "use_doc_orientation_classify" in out


def test_predict_param_whitelist_matches_measured_signature():
    """화이트리스트가 실측 시그니처에서 벗어나지 않도록 고정한다 (버전 업그레이드 회귀 방지).

    paddleocr 3.7.0의 PPStructureV3.predict()에 존재하지 않는 키를 넘기면 ValueError로
    추론이 실패하므로, 아래 두 목록은 코드와 함께 갱신되어야 한다.
    """
    must_include = {
        "use_doc_orientation_classify",
        "use_doc_unwarping",
        "use_textline_orientation",
        "use_table_recognition",
        "use_seal_recognition",
        "format_block_content",
        "layout_threshold",
        "layout_merge_bboxes_mode",
        "text_rec_score_thresh",
    }
    must_exclude = {"use_layout_detection", "use_ocr_for_image_block", "device", "cpu_threads"}
    assert must_include <= ocr_v5.PREDICT_PARAM_WHITELIST
    assert not (must_exclude & ocr_v5.PREDICT_PARAM_WHITELIST)


# ─── 한국어 인식기 설정 패치 ───

def _structure_v3_default_config() -> dict:
    """PP-StructureV3 기본 설정의 TextRecognition 배치를 재현한 축소판.

    a1에서 paddleocr 3.7.0 기본 설정을 덤프해 확인한 구조다 — TextRecognition이
    본문/표/도장 **세 곳**에 있고, 기본 모델은 한국어를 지원하지 않는 PP-OCRv5_server_rec이다.
    """
    return {
        "SubModules": {"LayoutDetection": {"model_name": "PP-DocLayout_plus-L"}},
        "SubPipelines": {
            "GeneralOCR": {
                "SubModules": {
                    "TextDetection": {"model_name": "PP-OCRv5_server_det"},
                    "TextRecognition": {"model_name": "PP-OCRv5_server_rec", "batch_size": 1},
                }
            },
            "TableRecognition": {
                "SubModules": {"TableClassification": {"model_name": "PP-LCNet_x1_0_table_cls"}},
                "SubPipelines": {
                    "GeneralOCR": {
                        "SubModules": {
                            "TextRecognition": {"model_name": "PP-OCRv5_server_rec", "batch_size": 1}
                        }
                    }
                },
            },
            "SealRecognition": {
                "SubPipelines": {
                    "SealOCR": {
                        "SubModules": {
                            "TextRecognition": {"model_name": "PP-OCRv5_server_rec", "batch_size": 1}
                        }
                    }
                }
            },
        },
    }


def test_patch_recognizers_replaces_every_text_recognition():
    """[Flow: Step 1 (기본 설정 트리) -> Step 2 (_patch_recognizers)
          -> Step 3 (본문/표/도장 세 인식기 모두 한국어 모델로 바뀌었는지 검증)]

    `text_recognition_model_name` kwarg는 본문(GeneralOCR)만 바꾼다. 표 셀과 도장 글자는
    한국어 미지원 모델로 남아 깨지므로, 설정 트리 전체를 훑어 교체해야 한다.
    """
    config = _structure_v3_default_config()
    stats = {"patched": 0}
    ocr_v5._patch_recognizers(config, stats)

    assert stats["patched"] == 3
    body = config["SubPipelines"]["GeneralOCR"]["SubModules"]["TextRecognition"]
    table = config["SubPipelines"]["TableRecognition"]["SubPipelines"]["GeneralOCR"]["SubModules"]["TextRecognition"]
    seal = config["SubPipelines"]["SealRecognition"]["SubPipelines"]["SealOCR"]["SubModules"]["TextRecognition"]
    for name, node in (("body", body), ("table", table), ("seal", seal)):
        assert node["model_name"] == ocr_v5.V5_REC_MODEL, name
        assert node["batch_size"] == ocr_v5.V5_REC_BATCH_SIZE, name
    # 인식기가 아닌 모듈은 건드리지 않는다.
    assert config["SubModules"]["LayoutDetection"]["model_name"] == "PP-DocLayout_plus-L"
    assert (
        config["SubPipelines"]["GeneralOCR"]["SubModules"]["TextDetection"]["model_name"]
        == "PP-OCRv5_server_det"
    )


def test_patch_recognizers_walks_lists():
    """리스트 안에 중첩된 인식기도 교체한다 (설정 스키마 변화 대비)."""
    config = {"items": [{"SubModules": {"TextRecognition": {"model_name": "x"}}}]}
    stats = {"patched": 0}
    ocr_v5._patch_recognizers(config, stats)
    assert stats["patched"] == 1
    assert config["items"][0]["SubModules"]["TextRecognition"]["model_name"] == ocr_v5.V5_REC_MODEL


def test_patch_recognizers_leaves_layout_model_alone_by_default(monkeypatch):
    """PADDLEOCR_V5_LAYOUT_MODEL이 비어 있으면 레이아웃 모델은 건드리지 않는다."""
    monkeypatch.setattr(ocr_v5, "V5_LAYOUT_MODEL", "")
    config = _structure_v3_default_config()
    stats = {"patched": 0}
    ocr_v5._patch_recognizers(config, stats)
    assert config["SubModules"]["LayoutDetection"]["model_name"] == "PP-DocLayout_plus-L"
    assert "layout_patched" not in stats


def test_patch_recognizers_swaps_layout_model_when_configured(monkeypatch):
    """[Flow: Step 1 (레이아웃 모델 지정) -> Step 2 (_patch_recognizers)
          -> Step 3 (LayoutDetection.model_name이 교체되는지 검증)]

    paddlex 기본 레이아웃 모델은 가장 큰 변형(PP-DocLayout_plus-L)이라 CPU에서 비싸다.
    """
    monkeypatch.setattr(ocr_v5, "V5_LAYOUT_MODEL", "PP-DocLayout-S")
    config = _structure_v3_default_config()
    stats = {"patched": 0}
    ocr_v5._patch_recognizers(config, stats)
    assert config["SubModules"]["LayoutDetection"]["model_name"] == "PP-DocLayout-S"
    assert stats["layout_patched"] == 1
    # 인식기 교체는 그대로 동작한다.
    assert stats["patched"] == 3


def test_korean_config_path_writes_patched_yaml(tmp_path, monkeypatch):
    """[Flow: Step 1 (가짜 기본 설정 YAML) -> Step 2 (_korean_config_path)
          -> Step 3 (기록된 YAML의 모든 인식기가 한국어 모델인지 검증)]"""
    yaml = pytest.importorskip("yaml")

    default_path = tmp_path / "PP-StructureV3.yaml"
    default_path.write_text(yaml.safe_dump(_structure_v3_default_config()), encoding="utf-8")

    monkeypatch.setattr(ocr_v5, "_find_default_config", lambda: default_path)
    monkeypatch.setattr(ocr_v5, "_patched_config_path", None)
    monkeypatch.setattr(ocr_v5, "_patched_config_failed", False)

    out = ocr_v5._korean_config_path()
    assert out is not None
    written = yaml.safe_load(Path(out).read_text(encoding="utf-8"))

    found = []

    def collect(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "TextRecognition" and isinstance(value, dict):
                    found.append(value["model_name"])
                else:
                    collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(written)
    assert len(found) == 3
    assert set(found) == {ocr_v5.V5_REC_MODEL}


def test_korean_config_path_returns_none_when_config_missing(monkeypatch):
    """기본 설정을 못 찾으면 None을 돌려주고, 호출자는 본문만 한국어인 상태로 계속 진행한다."""
    monkeypatch.setattr(ocr_v5, "_find_default_config", lambda: None)
    monkeypatch.setattr(ocr_v5, "_patched_config_path", None)
    monkeypatch.setattr(ocr_v5, "_patched_config_failed", False)
    assert ocr_v5._korean_config_path() is None


def test_rec_batch_size_defaults_to_one():
    """인식 배치 크기를 올리면 오히려 느려진다 (a1 실측: 1→113s/pg, 8→130s/pg, 품질 동일).

    "배치를 키우면 빠르다"는 직관으로 기본값이 다시 올라가는 것을 막는다.
    """
    assert ocr_v5.V5_REC_BATCH_SIZE == 1


def test_layout_model_defaults_to_paddlex_default():
    """레이아웃 모델은 기본값(빈 문자열=paddlex 기본)이어야 한다.

    PP-DocLayout-S는 한국어 스캔 표에서 레이아웃 검출 0건 → 마크다운/표가 통째로 비었다
    (a1 실측). 속도 이득도 작아서 낮출 이유가 없다.
    """
    assert ocr_v5.V5_LAYOUT_MODEL == ""


def test_det_model_defaults_to_server():
    """검출 모델 기본값은 품질 우선(server)이다 (mobile은 34% 빠르지만 검출 라인 -2%)."""
    assert ocr_v5.V5_DET_MODEL == "PP-OCRv5_server_det"


def test_mkldnn_defaults_off():
    """oneDNN은 paddlepaddle 3.3.1에서 PP-StructureV3 추론 중 크래시한다 (a1 실측).

    기본값이 다시 켜지면 프로덕션 OCR이 전량 실패하므로 고정한다.
    """
    assert ocr_v5.V5_ENABLE_MKLDNN is False


def test_reset_pool_clears_instances(monkeypatch):
    """reset_pool()이 풀과 생성 카운터를 비워 pool_size 재측정이 가능해야 한다."""
    monkeypatch.setattr(ocr_v5, "_pool", None)
    monkeypatch.setattr(ocr_v5, "_created", 3)
    ocr_v5._get_pool()
    assert ocr_v5._pool is not None
    ocr_v5.reset_pool()
    assert ocr_v5._pool is None
    assert ocr_v5._created == 0


# ─── predict_page / predict_pages ───

def _structure_v3_raw() -> dict:
    """PP-StructureV3 res.json 형태의 최소 페이지 결과 (bbox는 이미지 픽셀 좌표, top-left)."""
    return {
        "parsing_res_list": [
            {
                "block_label": "text",
                "block_content": "계약서",
                "block_bbox": _FakeArray([10, 20, 110, 60]),
            }
        ],
        "overall_ocr_res": {
            "rec_texts": ["계약서"],
            "rec_boxes": _FakeArray([[10, 20, 110, 60]]),
        },
        "doc_preprocessor_res": {"angle": 0},
    }


def test_predict_page_returns_aistudio_compatible_shape(tmp_path, fake_lease):
    """[Flow: Step 1 (PP-StructureV3 형태 결과를 반환하는 가짜 파이프라인)
          -> Step 2 (predict_page 호출) -> Step 3 (markdown/layout/page_angle 반환 검증)
          -> Step 4 (bbox가 0~1 정규화되었는지 검증)]

    layout은 main._extract_layout_from_result를 통과해 AI Studio 경로와 동일한
    0~1 정규화 좌표로 내려와야 한다 (core/ocr_layout.py, core/pdf_text_layer.py의 입력 규약).
    """
    img = _png(tmp_path, "page-001.png", (200, 100))
    fake_lease([_FakeRes(_structure_v3_raw(), {"markdown_texts": "계약서"})])

    out = ocr_v5.predict_page(img, params=None, layout_extractor=_v5_layout_extractor)

    assert out["markdown"] == "계약서"
    assert out["page_angle"] == 0
    layout = out["layout"]
    assert layout["_coordinate_system"] == "normalized"
    assert layout["_page_width_px"] == 200
    assert layout["_page_height_px"] == 100
    bbox = layout["parsing_res_list"][0]["block_bbox"]
    assert all(0.0 <= v <= 1.0 for v in bbox), bbox
    # x는 폭으로 나눈 값이 그대로 유지된다.
    assert bbox[0] == pytest.approx(10 / 200)
    assert bbox[2] == pytest.approx(110 / 200)
    # y도 정확히 검증한다. 픽스처 입력은 top-left(이미지 픽셀)이므로 뒤집히면 안 된다.
    # 범위(0~1)만 보면 상하 반전을 놓친다 — 실제로 그렇게 놓쳤다.
    # 자세한 회귀 테스트: tests/test_layout_coordinate_origin.py
    assert bbox[1] == pytest.approx(20 / 100)
    assert bbox[3] == pytest.approx(60 / 100)
    # rec_boxes도 함께 정규화되어야 한다 (searchable PDF 텍스트 레이어의 입력).
    assert all(0.0 <= v <= 1.0 for v in layout["overall_ocr_res"]["rec_boxes"][0])


def test_predict_page_passes_filtered_params_to_pipeline(tmp_path, fake_lease):
    """predict()에 전달되는 kwargs가 화이트리스트를 통과한 값인지 확인한다."""
    img = _png(tmp_path, "page-001.png", (200, 100))
    record: list = []
    fake_lease([_FakeRes(_structure_v3_raw())], record=record)

    ocr_v5.predict_page(
        img,
        params={"layout_threshold": 0.7, "use_ocr_for_image_block": True, "use_doc_unwarping": True},
    )

    _path, kwargs = record[0]
    assert kwargs["layout_threshold"] == 0.7
    # 왜곡 보정은 추천값이 True여도 강제 off (bbox 역매핑 불가)
    assert kwargs["use_doc_unwarping"] is False
    # PP-StructureV3가 모르는 키는 넘기지 않는다 (paddlex가 ValueError로 거부)
    assert "use_ocr_for_image_block" not in kwargs


def test_predict_page_without_extractor_returns_raw_layout(tmp_path, fake_lease):
    """layout_extractor가 없으면 정규화하지 않은 원본 dict를 그대로 돌려준다."""
    img = _png(tmp_path, "page-001.png", (200, 100))
    fake_lease([_FakeRes(_structure_v3_raw())])
    out = ocr_v5.predict_page(img, layout_extractor=None)
    assert out["layout"]["parsing_res_list"][0]["block_bbox"] == [10, 20, 110, 60]


def test_predict_page_empty_output(tmp_path, fake_lease):
    """파이프라인이 결과를 내지 않으면 빈 페이지 결과를 반환한다 (예외 아님)."""
    img = _png(tmp_path, "page-001.png", (200, 100))
    fake_lease([])
    out = ocr_v5.predict_page(img)
    assert out == {"markdown": "", "layout": {}, "page_angle": -1}


def test_predict_pages_isolates_page_failures(tmp_path, fake_lease):
    """[Flow: Step 1 (2번째 페이지에서 예외) -> Step 2 (predict_pages 호출)
          -> Step 3 (실패 페이지만 빈 결과, 나머지는 정상인지 검증)]

    100페이지 중 한 장의 실패가 전체 작업을 되돌리지 않아야 한다.
    """
    imgs = [_png(tmp_path, f"page-{i:03d}.png", (200, 100)) for i in range(1, 4)]
    fake_lease([
        _FakeRes(_structure_v3_raw(), {"markdown_texts": "p1"}),
        RuntimeError("inference exploded"),
        _FakeRes(_structure_v3_raw(), {"markdown_texts": "p3"}),
    ])

    out = ocr_v5.predict_pages(imgs, layout_extractor=_extract_layout_from_result, max_workers=1)

    assert len(out) == 3
    assert out[0]["markdown"] == "p1"
    assert "OCR 실패" in out[1]["markdown"]
    assert out[1]["layout"] == {}
    assert out[2]["markdown"] == "p3"


def test_predict_pages_empty_input():
    assert ocr_v5.predict_pages([]) == []
