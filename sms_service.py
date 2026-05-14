import hashlib
import hmac
import json
import os
import re
import uuid
from datetime import datetime

import boto3
import requests

from config import (
    DYNAMODB_TABLE_NAME,
    KST,
    SOLAPI_API_KEY,
    SOLAPI_API_SECRET,
    SOLAPI_SENDER,
)


dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(DYNAMODB_TABLE_NAME)


def extract_message_title(message):
    """메시지에서 제목 추출 (대괄호로 감싸진 첫 번째 줄)"""
    # [ABC X SAMPLE 안내] 같은 패턴 찾기
    match = re.search(r'\[([^\]]+)\]', message)
    if match:
        return match.group(0)  # 대괄호 포함해서 반환

    # 대괄호가 없으면 첫 줄 반환
    first_line = message.strip().split('\n')[0]
    return first_line[:50] if len(first_line) > 50 else first_line


def save_sms_history_to_dynamodb(user_id, message_type, message, phone_numbers, result):
    """SMS 발송 기록을 DynamoDB에 저장"""
    try:
        # 한국 시간으로 현재 시간 가져오기
        now_kst = datetime.now(KST)

        # 발송 결과 파싱
        count = result.get('count', {})
        total = count.get('total', 0)
        success = count.get('registeredSuccess', 0)
        failed = count.get('registeredFailed', 0)

        balance = result.get('balance', {})
        cost = balance.get('sum', 0)

        # 메시지 제목 추출
        title = extract_message_title(message)

        # DynamoDB에 저장할 아이템
        item = {
            'id': str(uuid.uuid4()),  # 고유 ID (파티션 키)
            'send_date': now_kst.strftime('%Y-%m-%d'),  # 발송 날짜 (정렬 키로 사용 가능)
            'send_time': now_kst.strftime('%H:%M:%S'),  # 발송 시간
            'send_datetime_kst': now_kst.strftime('%Y-%m-%d %H:%M:%S'),  # 전체 날짜시간
            'timestamp': int(now_kst.timestamp()),  # Unix timestamp
            'title': title,  # 메시지 제목
            'message_type': message_type,  # ot, education, location
            'total_count': total,  # 전체 발송 건수
            'success_count': success,  # 성공 건수
            'failed_count': failed,  # 실패 건수
            'cost': cost,  # 비용 (원)
            'sender_user_id': user_id,  # 발송자 Slack User ID
            'status': result.get('status', 'UNKNOWN')  # 발송 상태
        }

        # DynamoDB에 저장
        table.put_item(Item=item)

        print(f"SMS history saved to DynamoDB: {item['id']}")
        return True

    except Exception as e:
        print(f"Error saving SMS history to DynamoDB: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return False


def send_sms_via_solapi(phone_numbers, message, sender_number=None):
    """솔라피 API로 SMS 발송"""
    try:
        url = "https://api.solapi.com/messages/v4/send-many"

        # 발신번호 결정 (파라미터 > 환경변수)
        from_number = sender_number or SOLAPI_SENDER

        # HMAC 인증 - ISO 8601 형식 사용
        timestamp = datetime.utcnow().isoformat() + 'Z'
        salt = os.urandom(16).hex()
        data = timestamp + salt
        signature = hmac.new(
            SOLAPI_API_SECRET.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "Authorization": f"HMAC-SHA256 apiKey={SOLAPI_API_KEY}, date={timestamp}, salt={salt}, signature={signature}",
            "Content-Type": "application/json"
        }

        # 메시지 리스트 생성
        messages = []
        for phone in phone_numbers:
            messages.append({
                "to": phone,
                "from": from_number,
                "text": message
            })

        payload = {
            "messages": messages
        }

        print(f"Sending SMS to {len(messages)} recipients from {from_number}")
        print(f"Timestamp (ISO 8601): {timestamp}")
        print(f"Message: {message}")

        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response_data = response.json()

        print(f"Solapi response status: {response.status_code}")
        print(f"Solapi response: {json.dumps(response_data, ensure_ascii=False)}")

        return response_data

    except Exception as e:
        print(f"Error in send_sms_via_solapi: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return {"error": str(e)}
