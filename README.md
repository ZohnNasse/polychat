# PolyChat

하나의 고민을 **세 각도(찬성·부정·엉뚱)로 서로 다른 AI에게 동시에 던지고**, 그 답을 종합·투표·최종 결론까지 끌고 가는 1인용 "감별진단" 콘솔이다. 결론이 아니라 *검증할 가설*을 뽑는 게 목적이다.

## 어떻게 도는가

PolyChat은 **네 컴퓨터의 크롬에 붙어** Claude·ChatGPT·Gemini의 웹 UI를 직접 조종한다(Playwright CDP). 즉 클라우드에 올리는 서비스가 아니라, **각자 자기 맥에서 자기 로그인으로 돌리는 로컬 앱**이다. 서버·크롬·로그인이 전부 네 기기에 있다.

## 요구사항

- Python 3.11 이상
- Google Chrome (데스크톱)
- Claude·ChatGPT·Gemini 계정 (쓰려는 것만)

## 설치

```bash
git clone https://github.com/ZohnNasse/polychat
cd polychat
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 실행 & 최초 로그인

```bash
python main.py
```

1. 브라우저에서 `http://localhost:7777` 접속.
2. 첫 사용 시 앱이 **전용 프로필 크롬 창**을 자동으로 띄운다(디버그 포트 9223, 평소 쓰는 크롬과 분리됨).
3. 그 창에서 Claude·ChatGPT·Gemini에 **한 번씩 로그인**한다. 세션은 `profiles/`에 남아 다음부턴 자동 유지된다.
4. 이후 PolyChat 화면 하단에 고민을 입력하면 세 모델이 각자 역할로 답하고, 종합→투표→최종 결론으로 이어진다.

`source .venv/bin/activate` 없이 한 줄로 띄우려면 `.venv/bin/python main.py`.

## 설정

- **역할·모델 매핑, 프롬프트**: 웹 UI의 "역할 설정" 패널에서 편집(자동 저장, `settings.json`).
- **포트·CDP·셀렉터**: `config.yaml`. 각 서비스 UI가 바뀌어 응답을 못 잡으면 `agents.*.selectors`만 고치면 된다(코드 수정 불필요).

## 주의

- **개인용 도구다.** 웹 UI를 자동 조종하는 방식이라 각 서비스 약관상 회색지대이고, 공개 다중사용자 서비스로 배포하는 용도가 아니다.
- 서비스 UI가 개편되면 `config.yaml`의 셀렉터를 갱신해야 한다.
- `profiles/`, `settings.json`, `diagnoses.md`는 개인 데이터라 `.gitignore`로 커밋에서 제외돼 있다.
