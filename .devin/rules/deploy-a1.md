---
trigger: model_decision
description: When deploying the app
---

deploy_develop.sh 로 a1의 develop 에 배포할 수 있다. 현재 백엔드,db가 a1의 develop 브랜치와 연결돼있다.

배포 전에:
1. 전체 변경 부분을 AGENTS.md 에 upsert/update(변경부분과 배치되는 것은 삭제해)
2. 커밋
3. 푸시
4. 배포

메인브랜치를 이용한 프로덕션배포는 명시적으로 사용자가 지시하지 않은 이상 하지마.