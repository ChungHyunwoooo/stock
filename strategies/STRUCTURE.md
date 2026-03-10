# strategies/ 구조

```
strategies/
  registry.json              ← 전체 전략 메타데이터 (single source of truth)
  STRUCTURE.md               ← 이 파일
  {strategy_id}/
    definition.json          ← 파라미터 + entry/exit/risk (코드가 로드)
    research.md              ← 연구 내용, 백테스트 결과, 폐기 사유
    docs/                    ← 참고 자료 (PDF, 이미지 등)
```

## 규칙

- **registry.json이 원본**: status (active/deprecated) 여기서 관리
- **전략 추가**: registry에 항목 추가 → dir 생성 → definition.json + research.md
- **전략 폐기**: registry의 status를 deprecated로 변경 + research.md에 사유 기록
- **파일명에 버전 금지**: v1/v2 붙이지 않음, git으로 관리
- **definition.json**: StrategyDefinition 스키마 (engine/schema.py)
- **research.md**: 자유 형식, 최소 폐기 사유 or 채택 근거 포함
