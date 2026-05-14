import csv
import io
import re

import requests


PHONE_PATTERN = re.compile(r'010-?[0-9]{4}-?[0-9]{4}')


def normalize_phone_number(phone):
    """전화번호에서 구분자를 제거해 01012345678 형식으로 정규화"""
    return phone.replace('-', '').replace(' ', '')


def extract_phone_numbers_from_google_sheet(sheet_url):
    """구글 시트에서 전화번호 추출"""
    try:
        # 구글 시트 ID 추출
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', sheet_url)
        if not match:
            return None, "올바른 구글 시트 URL이 아닙니다."

        spreadsheet_id = match.group(1)

        # gid 추출 (시트 ID)
        gid_match = re.search(r'[#&]gid=([0-9]+)', sheet_url)
        gid = gid_match.group(1) if gid_match else '0'

        # CSV로 export
        csv_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid}"

        print(f"Fetching Google Sheet: {csv_url}")
        response = requests.get(csv_url, timeout=10)

        print(f"Response status: {response.status_code}")
        if response.status_code != 200:
            return None, f"구글 시트 접근 실패 (HTTP {response.status_code}). 공유 설정을 '링크가 있는 모든 사용자'로 설정해주세요."

        # CSV 파싱
        csv_content = response.content.decode('utf-8')
        print(f"CSV content preview: {csv_content[:200]}")

        csv_reader = csv.reader(io.StringIO(csv_content))

        phone_numbers = []

        # 모든 셀 검색
        row_count = 0
        for row in csv_reader:
            row_count += 1
            for cell in row:
                if cell:
                    cell_str = str(cell).strip()
                    # 전화번호 패턴 찾기
                    matches = PHONE_PATTERN.findall(cell_str)
                    for match in matches:
                        # 하이픈 제거하고 정규화
                        phone = normalize_phone_number(match)
                        if len(phone) == 11 and phone not in phone_numbers:
                            phone_numbers.append(phone)

        print(f"Processed {row_count} rows, found {len(phone_numbers)} phone numbers")
        return phone_numbers, None

    except Exception as e:
        print(f"Error extracting phone numbers: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return None, f"오류 발생: {str(e)}"


def extract_phone_numbers_from_text(text):
    """직접 입력한 텍스트에서 전화번호 추출"""
    if not text:
        return []

    phone_numbers = []

    # 줄바꿈, 쉼표, 공백 등으로 분리된 번호 찾기
    matches = PHONE_PATTERN.findall(text)

    for match in matches:
        # 하이픈 제거하고 정규화
        phone = normalize_phone_number(match)
        if len(phone) == 11 and phone not in phone_numbers:
            phone_numbers.append(phone)

    print(f"Extracted {len(phone_numbers)} phone numbers from manual input")
    return phone_numbers
