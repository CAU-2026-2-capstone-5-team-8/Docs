# 다이어그램 원본

- matching-flow: 목표 설계. 본문 속성 분석과 독립 평가 경로는 제안이며 미구현.
- question-lifecycle: 제안하는 문항 준비 및 사전/사후 용도 분리.
- runtime-architecture: 현재 구현된 웹 서비스 경로. 가동/배포 상태를 나타내지 않음.

Mermaid 원본과 SVG를 함께 관리한다. 동일 이름의 SVG는 해당 `.mmd`를 렌더링한 것이다.
도식 자체에는 실제 책 본문·계정·사용자 정보가 없다.

작성 시 `@mermaid-js/mermaid-cli 12.0.0`과 로컬 Chrome으로 렌더링했고 PNG에서도 글자/연결을 확인했다.
프로젝트 런타임 의존성에는 추가하지 않았다. 설정은 `render-config.json`이다.

```sh
mmdc -i matching-flow.mmd -o matching-flow.svg -c render-config.json -b white
```

다른 두 도식도 같은 설정으로 렌더링한다. `.mmd`를 수정하면 `.svg`도 다시 생성하고 눈으로 확인한다.
