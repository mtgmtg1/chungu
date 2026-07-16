# [Flow: Stage 1 (LibreOffice + unoserver 설치) -> Stage 2 (unoserver listener 실행)]
# PROOF 문서(PPTX/DOCX/HWP/ODT)를 PDF로 변환하는 전용 서비스.
# 백엔드 컨테이너와 파일시스템을 공유하지 않고 XMLRPC로 바이너리 데이터를 주고받는다.
FROM python:3.11-slim

# apt 캐시 최소화
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer \
    libreoffice-impress \
    libreoffice-l10n-ko \
    libreoffice-help-ko \
    # unoserver 서버는 시스템 Python의 python3-uno가 필요하다.
    python3 \
    python3-pip \
    python3-uno \
    # CJK 폰트 (한글/중국어/일본어 렌더링)
    fonts-noto-cjk \
    fonts-nanum \
    fonts-unfonts-core \
    # locale
    locales \
    # 보안/네트워크
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 한국어 locale 생성
RUN sed -i 's/^# *\(ko_KR.UTF-8\)/\1/' /etc/locale.gen && \
    sed -i 's/^# *\(ja_JP.UTF-8\)/\1/' /etc/locale.gen && \
    sed -i 's/^# *\(zh_CN.UTF-8\)/\1/' /etc/locale.gen && \
    locale-gen

ENV LANG=ko_KR.UTF-8
ENV LC_ALL=ko_KR.UTF-8

# python:3.11-slim 이미지의 기본 /usr/local/bin/python3는 python3-uno가 없다.
# Debian apt의 /usr/bin/python3를 사용해 unoserver 서버를 실행한다.
RUN /usr/bin/python3 -m pip install --break-system-packages --no-cache-dir unoserver==3.7

# LibreOffice 사용자 프로필/임시 파일을 /tmp에 생성하도록 제한
ENV HOME=/tmp
ENV XDG_CONFIG_HOME=/tmp/.config
ENV XDG_CACHE_HOME=/tmp/.cache

EXPOSE 2003

CMD ["/usr/bin/python3", "-m", "unoserver.server", \
     "--interface", "0.0.0.0", \
     "--port", "2003", \
     "--uno-interface", "127.0.0.1", \
     "--uno-port", "2002", \
     "--conversion-timeout", "120"]
