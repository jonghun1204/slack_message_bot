import os
from datetime import timezone, timedelta


# 허용된 사용자 리스트
ALLOWED_USERS = [
    "U05JLKA5FLG",
    "U06GSJW0B37",
    "U059F7CKA7J",
    "U04V0HG569X",
    "U06AG9QBVHT",
    "U09LNGBJV26"
]

# 솔라피 설정
SOLAPI_API_KEY = os.environ.get("SOLAPI_API_KEY")
SOLAPI_API_SECRET = os.environ.get("SOLAPI_API_SECRET")
SOLAPI_SENDER = os.environ.get("SOLAPI_SENDER")  # 기본값 (fallback)

# 발신번호 목록
SENDER_NUMBERS = [
    {"value": "01032216282", "label": "010-3221-6282"},
    {"value": "01051971426", "label": "010-5197-1426"},
    {"value": "01029665183", "label": "010-2966-5183"}
]

# DynamoDB 설정
DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "sms-send-history")

# 한국 시간대
KST = timezone(timedelta(hours=9))

# 메시지 타입별 기본 메시지
DEFAULT_MESSAGES = {
    "ot": """[ABC X SAMPLE 안내]
안녕하세요, ABC입니다.
SAMPLE OT가 진행될 예정입니다.

사전에 아래 두 가지를 확인해 주세요.
1.SAMPLE 18:00 OT 참여
2.슬랙 워크스페이스 입장 (표시이름 "SAMPLE" 으로 변경해주세요.)
3.스킬빌더 강의 수강 후 수료증을 슬랙 채널에 제출해주세요.

1.오리엔테이션
SAMPLE 18:00 OT 참여
구글 미트 링크: SAMPLE_LINK
2.슬랙 워크스페이스 입장 (표시이름을 "SAMPLE" 으로 변경)
Slack 링크: SAMPLE_LINK

""",
    "education": """[ABC X SAMPLE 안내]
안녕하세요, ABC입니다.

슬랙 워크스페이스 입장 (표시이름을 "SAMPLE" 으로 변경)
Slack 링크: SAMPLE_LINK""",
    "location": """[ABC X SAMPLE 교육 안내]

안녕하세요. ABC입니다.
내일 장소 및 일시 안내드립니다.

장소: SAMPLE 교육장
일시: 10:00 ~ 17:00
준비물: 노트북, 충전기

늦으시거나 참여가 어려울 경우 해당 번호로 연락주시면 감사하겠습니다."""
}

# 메시지 타입별 플레이스홀더
MESSAGE_PLACEHOLDERS = {
    "ot": "OT 안내 메시지를 수정하거나 새로 작성하세요",
    "education": "교육 안내 메시지를 수정하거나 새로 작성하세요",
    "location": "장소/시간 안내 메시지를 수정하거나 새로 작성하세요"
}
