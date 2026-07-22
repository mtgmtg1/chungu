---
trigger: model_decision
description: When distributing the app
---

배포는 deploy_develop.sh 를 실행해서 develop브랜치를 a1서버에 배포 해야한다.

배포 전에:
1. 전체 변경 부분을 AGENTS.md 에 upsert/update(변경부분과 배치되는 것은 삭제해)
2. 커밋
3. 푸시
4. 배포

메인브랜치에 대한 머지는 명시적인 요청없이는 하지마. 프로덕션배포(deploy_a1.sh)는 명시적으로 사용자가 지시하지 않은 이상 하지마.