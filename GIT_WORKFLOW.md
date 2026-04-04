# Git 워크플로우 & 배포 가이드

## 배포 구조

| 구분 | 호스팅 | 배포 트리거 |
|------|--------|------------|
| Frontend (Next.js) | Vercel | `main` push 시 자동 배포 |
| Backend (Python) | GCP VM (PM2) | `main` push 후 VM에서 수동 pull + restart |

---

## 브랜치 전략

```
main (배포용) ← 검증된 코드만 merge
  ↑
dev  (작업용) ← 모든 개발은 여기서
```

- **main**: 배포 브랜치. 직접 커밋하지 않는다.
- **dev**: 개발 브랜치. 모든 작업은 여기서 진행.

---

## 일상 작업 흐름

### 1단계: 개발 (dev 브랜치)

```bash
git checkout dev              # dev 브랜치 확인
# 코드 수정...
git add <수정된 파일>
git commit -m "feat: 설명"
git push origin dev           # dev에 push (배포 안 됨, 안전)
```

### 2단계: 배포 (main으로 merge)

```bash
git checkout main             # main으로 이동
git merge dev                 # dev 내용을 main에 병합
git push origin main          # push → Vercel 자동 배포
git checkout dev              # 다시 dev로 돌아오기
```

### 3단계: Backend 업데이트 (Python 변경 시)

```bash
# GCP VM에 SSH 접속
gcloud compute ssh <VM이름> --zone <zone>

# VM 내부에서
cd ~/stock
git pull origin main
pm2 restart all               # 또는: pm2 restart stock-agent

# 로그 확인
pm2 logs --lines 20
```

> Frontend만 수정한 경우 → 2단계까지만 하면 끝 (Vercel 자동 배포)
> Backend도 수정한 경우 → 3단계까지 진행

---

## 커밋 메시지 규칙

```
<타입>: <설명>
```

| 타입 | 용도 | 예시 |
|------|------|------|
| `feat` | 신규 기능 | `feat: KIS 잔고 조회 API 추가` |
| `fix` | 버그 수정 | `fix: 시장 국면 판별 오류 수정` |
| `conf` | 전략/설정 변경 | `conf: 손절 기준 -1.5% → -2.0%` |
| `ui` | 프론트엔드 변경 | `ui: 계좌 페이지 차트 추가` |
| `refactor` | 리팩토링 | `refactor: 데이터수집 에이전트 구조 개선` |
| `docs` | 문서 수정 | `docs: CLAUDE.md 통신 프로토콜 업데이트` |

> `conf` 타입으로 전략 변경 이력을 추적할 수 있다.

---

## PM2 주요 명령어 (VM에서)

```bash
pm2 list                      # 실행 중인 프로세스 목록
pm2 restart all               # 전체 재시작
pm2 restart stock-agent       # 특정 앱 재시작
pm2 logs --lines 50           # 최근 로그 50줄
pm2 monit                     # 실시간 모니터링
pm2 stop all                  # 전체 중지
pm2 start ecosystem.config.js # 설정 파일로 시작
```

---

## 긴급 롤백

배포 후 문제 발생 시:

```bash
# 직전 커밋으로 되돌리기
git checkout main
git revert HEAD               # 최신 커밋을 취소하는 새 커밋 생성
git push origin main          # Vercel 자동 재배포

# VM도 업데이트
# SSH 접속 후
git pull origin main
pm2 restart all
```

> `git revert`는 이력을 보존하면서 되돌리므로 안전하다.

---

## 주의사항

1. **main에 직접 커밋하지 않는다** — 항상 dev에서 작업 후 merge
2. **push 전 확인** — `git branch`로 현재 브랜치 확인하는 습관
3. **민감 정보 주의** — `.env`, API 키 등은 절대 커밋하지 않음 (.gitignore 확인)
4. **큰 변경은 나눠서** — 프론트/백엔드 동시 변경 시 각각 커밋하면 추적이 쉬움
