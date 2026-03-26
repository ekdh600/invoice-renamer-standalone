# Invoice Renamer (견적서 파일명 자동 변경)

PDF 견적서에서 **상호명(발행 업체)** 과 **날짜(YYYYMMDD)** 를 추출해 파일명을 자동으로 바꿉니다.

- 기본: **로컬 우선** (LM Studio 비전 모델로 OCR → 텍스트에서 상호/날짜 추출)
- 옵션: CLOVA OCR 사용 가능 (`--clova`)

## 단독 실행(standalone) 안내

이 프로젝트는 `99-Projects/invoice-renamer/` 폴더만 따로 복사해도 실행 가능합니다.

- 입력 PDF/출력 폴더는 사용자가 지정합니다 (`--file/--dir`, `--out`)
- `.env`에는 **개인 키를 넣지 말고** 각자 환경에 맞게 설정하세요 (`.env.example` 제공)

## 요구사항

- Python **3.11+**
- (로컬 OCR 사용 시) **poppler**
- (로컬 OCR 사용 시) LM Studio에서 **비전(Vision) 모델** 실행

## 설치 (공통)

```bash
cd 99-Projects/invoice-renamer
pip install -r requirements.txt
pip install -e .
```

로컬 OCR을 쓰려면 `pdf2image` + poppler가 필요합니다.

### macOS (Homebrew)

```bash
brew install poppler
```

### Windows

#### 1) poppler 설치

`pdf2image`는 내부적으로 `pdftoppm`(poppler)을 호출합니다. Windows에서는 poppler를 설치하고 PATH에 추가해야 합니다.

- **권장(Chocolatey)**:

```powershell
choco install poppler -y
```

설치 후 새 PowerShell을 열고 확인:

```powershell
pdftoppm -h
```

만약 `pdftoppm`를 못 찾는다면, poppler의 `bin` 폴더가 PATH에 포함되었는지 확인하세요.

#### 2) LM Studio 실행 (로컬 OCR/추출용)

- LM Studio에서 비전 모델(예: `qwen/qwen2.5-vl-7b` 등)을 **로드**
- Local Server를 켜고 기본 주소가 `http://127.0.0.1:1234`인지 확인

## 환경변수

`.env.example`를 `.env`로 복사해서 값만 채워주세요.

### macOS/Linux

```bash
cp .env.example .env
```

### Windows (PowerShell)

```powershell
Copy-Item .env.example .env
```

`.env` 내용 예시:

- `LM_STUDIO_BASE_URL`: 보통 `http://127.0.0.1:1234`
- `LM_VISION_MODEL`: LM Studio에서 실행 중인 비전 모델 키

## 사용법

### 단일 파일

```bash
python -m invoice_renamer --file "/path/to/invoice.pdf" --out "./out"
```

### 디렉터리

```bash
python -m invoice_renamer --dir "./invoices" --out "./out"
```

### Windows 예시 (PowerShell)

```powershell
python -m invoice_renamer --file "C:\\invoices\\2.pdf" --out ".\\out"
python -m invoice_renamer --dir  "C:\\invoices"      --out ".\\out"
```

### CLOVA OCR 사용

```bash
python -m invoice_renamer --file "./invoices/2.pdf" --out "./out" --clova
```

## 출력 파일명 규칙

`{상호명}_{YYYYMMDD}.pdf`

날짜를 못 찾으면 `00000000`으로 저장합니다.

## 트러블슈팅

### `pdf2image` 관련 오류 / `pdftoppm` not found

- Windows: poppler 설치 및 PATH 반영 후 새 터미널에서 재시도
- macOS: `brew install poppler`

### LM Studio OCR이 실패하거나 너무 느림

- PDF가 크면 이미지가 커져서 실패할 수 있어, 내부적으로 **리사이즈(긴 변 1536px)** 후 전송합니다.
- 그래도 실패하면:
  - `--max-pages 1`로 줄여서 테스트
  - `--ocr-dpi`를 200→150으로 낮춰보기
  - LM Studio에서 **다른 비전 모델**로 교체

## 프롬프트

현재 코드에서 사용 중인 프롬프트 원문은 `invoice-renamer-prompts.md`에 정리되어 있습니다.
