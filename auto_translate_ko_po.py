import os
import re
import polib
from google.cloud import translate_v2 as translate

# 번역 대상 언어
TARGET_LANG = "ko"

# 이 스크립트가 있는 위치 (InvenTree 루트)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ===== 프론트엔드(Platform UI) 번역 파일 경로 =====
# 영어 원본
EN_PO_PATH = os.path.join(
    BASE_DIR,
    "src", "frontend", "src", "locales", "en", "messages.po",
)

# 한국어 번역 대상
KO_PO_PATH = os.path.join(
    BASE_DIR,
    "src", "frontend", "src", "locales", "ko", "messages.po",
)

# 영문/기호만으로 된 문자열인지 확인하는 패턴
ASCII_RE = re.compile(r"^[\x00-\x7F\s\d\W]+$")


def is_likely_english(text: str) -> bool:
    """
    msgstr가 '사실상 영어'인지 판단:
    - 비어 있거나
    - ASCII 문자(영문/숫자/기호)만 있는 경우
    """
    if not text.strip():
        return True
    if ASCII_RE.match(text):
        return True
    return False


def get_client() -> translate.Client:
    """Google Translation 클라이언트 생성"""
    return translate.Client()


def translate_texts(client: translate.Client, texts: list[str]) -> list[str]:
    """여러 문자열을 한 번에 번역"""
    if not texts:
        return []
    results = client.translate(texts, target_language=TARGET_LANG, format_="text")
    return [r["translatedText"] for r in results]


def main() -> None:
    # 영어 파일 존재 확인
    if not os.path.exists(EN_PO_PATH):
        raise FileNotFoundError(f"영어 po 파일을 찾을 수 없음: {EN_PO_PATH}")

    print(f"[frontend] 영어 원본 : {EN_PO_PATH}")
    print(f"[frontend] 한국어 대상: {KO_PO_PATH}")

    en_po = polib.pofile(EN_PO_PATH)

    # 한국어 파일이 없으면 새로 만든다
    if os.path.exists(KO_PO_PATH):
        ko_po = polib.pofile(KO_PO_PATH)
    else:
        os.makedirs(os.path.dirname(KO_PO_PATH), exist_ok=True)
        ko_po = polib.POFile()
        ko_po.metadata = en_po.metadata.copy()
        ko_po.metadata["Language"] = TARGET_LANG

    # msgid -> ko entry 매핑
    ko_map = {e.msgid: e for e in ko_po}

    client = get_client()
    targets = []

    # 번역 대상 골라내기
    for en_entry in en_po:
        if not en_entry.msgid or en_entry.obsolete:
            continue

        ko_entry = ko_map.get(en_entry.msgid)

        # ko에 엔트리가 없으면 새로 만든다
        if not ko_entry:
            ko_entry = polib.POEntry(
                msgid=en_entry.msgid,
                msgid_plural=en_entry.msgid_plural,
                occurrences=en_entry.occurrences,
                comment=en_entry.comment,
            )
            ko_po.append(ko_entry)
            ko_map[en_entry.msgid] = ko_entry

        # plural 이 있는 경우 (거의 없겠지만 안전하게 처리)
        if en_entry.msgid_plural:
            plural_strs = [
                ko_entry.msgstr_plural.get(0, ""),
                ko_entry.msgstr_plural.get(1, ""),
            ]
            # 두 개 다 영어처럼 보이면 번역 대상
            if all(is_likely_english(s or "") for s in plural_strs):
                targets.append(("plural", en_entry, ko_entry))
        else:
            # 단수형: msgstr가 영어처럼 보이면 번역 대상
            base_text = ko_entry.msgstr or en_entry.msgstr or ""
            if is_likely_english(base_text):
                targets.append(("singular", en_entry, ko_entry))

    print(f"[frontend] 번역 대상 엔트리 개수: {len(targets)}")

    if not targets:
        print("[frontend] 새로 번역할 항목이 없습니다.")
        return

    BATCH_SIZE = 50
    for i in range(0, len(targets), BATCH_SIZE):
        batch = targets[i : i + BATCH_SIZE]

        singular_texts = []
        singular_entries = []

        plural_texts = []
        plural_entries = []

        for kind, en_entry, ko_entry in batch:
            if kind == "singular":
                singular_texts.append(en_entry.msgid)
                singular_entries.append((en_entry, ko_entry))
            else:
                plural_texts.extend([en_entry.msgid, en_entry.msgid_plural])
                plural_entries.append((en_entry, ko_entry))

        # 단수형 번역
        singular_results = []
        if singular_texts:
            singular_results = translate_texts(client, singular_texts)

        # 복수형 번역
        plural_results = []
        if plural_texts:
            plural_results = translate_texts(client, plural_texts)

        # 결과 반영: 단수
        idx = 0
        for en_entry, ko_entry in singular_entries:
            text_ko = singular_results[idx]
            idx += 1
            ko_entry.msgstr = text_ko

        # 결과 반영: 복수 (msgstr_plural[0], [1])
        idx = 0
        for en_entry, ko_entry in plural_entries:
            singular_ko = plural_results[idx]
            plural_ko = plural_results[idx + 1]
            idx += 2
            ko_entry.msgstr_plural[0] = singular_ko
            ko_entry.msgstr_plural[1] = plural_ko

        print(f"[frontend] {i + len(batch)} / {len(targets)} 개 처리 완료")

    ko_po.save(KO_PO_PATH)
    print(f"[frontend] 저장 완료: {KO_PO_PATH}")


if __name__ == "__main__":
    main()
