# Invoice Renamer Standalone

PII(개인정보) 보호 기반 지능형 PDF 파일명 자동화 시스템의 핵심 설계 및 LLM 프롬프트가 포함된 프로젝트입니다.
이 프로젝트는 **LangChain**과 **Local OCR/LLM**, **Microsoft Presidio**를 사용하여 스캔된 견적서의 파일명을 안전하게 `업체명_날짜.pdf` 형식으로 자동 변경합니다.

## 핵심 LLM 프롬프트 설계

이 시스템은 외부/로컬 LLM을 사용하여 마스킹된 텍스트나 OCR 결과에서 핵심 정보를 뽑아냅니다.
프롬프트는 다음과 같이 최적화되어 있습니다.

```text
System/User Prompt:

아래 견적서 텍스트에서 발행업체 상호명과 날짜를 추출해.
- 반드시 JSON만 출력: {"company_name":"...","date":"YYYYMMDD 또는 Unknown"}
- 상호는 '상호/업체명' 라벨의 회사명 우선
- '성명/이름/담당/귀하/부서'가 붙어 있으면 제거
- 날짜는 YYYYMMDD 형식, 없으면 Unknown

[견적서 텍스트]
{text}
[텍스트 끝]
```

## 주요 시스템 워크플로우

1. **Pre-processing (PDF -> 이미지)**: `pdf2image`를 통해 PDF를 해상도 최적화(DPI 변환).
2. **Local OCR (Vision LLM / PaddleOCR / CLOVA OCR)**: 로컬 혹은 외부 OCR을 거쳐 전체 텍스트를 추출.
3. **PII Masking (Microsoft Presidio)**: 사업자번호, 계좌번호, 주민등록번호, 연락처 등 민감 개인정보를 로컬 환경에서 먼저 마스킹.
4. **LLM Extraction**: 마스킹 된 안전한 정보를 프롬프트와 함께 LLM에 주입하여 `company_name`과 `date`를 JSON 구조화 포맷으로 돌려받음.
5. **Rename & Organize**: 추출 결과에 따라 파일명을 규칙 기반(Regex 정제)으로 치환 및 디렉터리 분배/저장.

## 주요 고려사항 (데이터 구조)

Pydantic을 통한 강제 파싱 모델:
- `company_name`: 견적서를 발행한 업체명 또는 상호명
- `date`: YYYYMMDD 형식의 날짜. 판독 불가시 `Unknown` 강제.
