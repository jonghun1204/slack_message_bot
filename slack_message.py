import os
import json
from datetime import datetime
from slack_bolt import App
from slack_bolt.adapter.aws_lambda import SlackRequestHandler

from config import (
    ALLOWED_USERS,
    DEFAULT_MESSAGES,
    KST,
    MESSAGE_PLACEHOLDERS,
    SENDER_NUMBERS,
)
from phone_numbers import (
    extract_phone_numbers_from_google_sheet,
    extract_phone_numbers_from_text,
)
from sms_service import (
    extract_message_title,
    save_sms_history_to_dynamodb,
    send_sms_via_solapi,
)

# Slack 앱 초기화
app = App(
    token=os.environ.get("BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
    process_before_response=True
)


# 사용자 권한 확인 함수
def is_user_allowed(user_id):
    """허용된 사용자인지 확인"""
    return user_id in ALLOWED_USERS

# 슬래시 명령어: 메시지 타입 선택 모달
@app.command("/문자발송")
def handle_command(ack, body, client):
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    
    # 권한 체크
    if not is_user_allowed(user_id):
        ack()
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="❌ 이 봇을 사용할 권한이 없습니다.\n관리자에게 문의하세요."
        )
        return
    
    ack()
    
    trigger_id = body["trigger_id"]
    
    # 메시지 타입 선택 모달
    client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "message_type_selection",
            "private_metadata": json.dumps({
                "user_id": user_id,
                "channel_id": channel_id
            }),
            "title": {"type": "plain_text", "text": "문자 발송"},
            "submit": {"type": "plain_text", "text": "다음"},
            "close": {"type": "plain_text", "text": "취소"},
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "📨 메시지 타입 선택"}
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "발송할 메시지 종류를 선택하세요."
                    }
                },
                {
                    "type": "input",
                    "block_id": "message_type_block",
                    "label": {"type": "plain_text", "text": "메시지 타입"},
                    "element": {
                        "type": "static_select",
                        "action_id": "message_type_select",
                        "placeholder": {"type": "plain_text", "text": "타입 선택"},
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": "🎓 OT 안내"},
                                "value": "ot"
                            },
                            {
                                "text": {"type": "plain_text", "text": "📚 교육 안내"},
                                "value": "education"
                            },
                            {
                                "text": {"type": "plain_text", "text": "📍 장소/시간 안내"},
                                "value": "location"
                            }
                        ]
                    }
                }
            ]
        }
    )

# 메시지 타입 선택 모달 제출
@app.view("message_type_selection")
def handle_type_selection(ack, body, client, view):
    try:
        metadata = json.loads(view.get('private_metadata', '{}'))
        user_id = metadata.get('user_id')
        channel_id = metadata.get('channel_id')
        
        # 권한 재확인
        if not is_user_allowed(user_id):
            ack()
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="❌ 이 봇을 사용할 권한이 없습니다."
            )
            return
        
        # 선택한 메시지 타입
        message_type = view['state']['values']['message_type_block']['message_type_select']['selected_option']['value']
        
        # 타입별 모달 타이틀과 설명
        modal_config = {
            "ot": {
                "title": "OT 문자 발송",
                "emoji": "🎓",
                "description": "OT 안내 문자를 발송합니다."
            },
            "education": {
                "title": "교육 문자 발송",
                "emoji": "📚",
                "description": "교육 일정 안내 문자를 발송합니다."
            },
            "location": {
                "title": "장소/시간 안내",
                "emoji": "📍",
                "description": "장소 및 시간 안내 문자를 발송합니다."
            }
        }
        
        config = modal_config.get(message_type, modal_config["ot"])
        placeholder = MESSAGE_PLACEHOLDERS.get(message_type, MESSAGE_PLACEHOLDERS["ot"])
        default_message = DEFAULT_MESSAGES.get(message_type, DEFAULT_MESSAGES["ot"])
        
        # 다음 모달을 스택에 추가 (자동으로 뒤로가기 버튼 생성)
        ack(
            response_action="push",
            view={
                "type": "modal",
                "callback_id": f"google_sheet_{message_type}_modal",
                "private_metadata": json.dumps({
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "message_type": message_type
                }),
                "title": {"type": "plain_text", "text": config["title"]},
                "submit": {"type": "plain_text", "text": "다음"},
                "close": {"type": "plain_text", "text": "취소"},
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": f"{config['emoji']} {config['description']}"}
                    },
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*1단계: 발신번호 선택*"
                        }
                    },
                    {
                        "type": "input",
                        "block_id": "sender_number_block",
                        "label": {"type": "plain_text", "text": "📞 발신번호"},
                        "element": {
                            "type": "static_select",
                            "action_id": "sender_number_select",
                            "placeholder": {"type": "plain_text", "text": "발신번호 선택"},
                            "initial_option": {
                                "text": {"type": "plain_text", "text": SENDER_NUMBERS[0]["label"]},
                                "value": SENDER_NUMBERS[0]["value"]
                            },
                            "options": [
                                {
                                    "text": {"type": "plain_text", "text": sender["label"]},
                                    "value": sender["value"]
                                }
                                for sender in SENDER_NUMBERS
                            ]
                        }
                    },
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*2단계: 수신자 전화번호 입력*\n아래 두 가지 방법 중 하나 이상을 사용하세요."
                        }
                    },
                    {
                        "type": "input",
                        "block_id": "sheet_url_block",
                        "label": {"type": "plain_text", "text": "📊 구글 시트 URL (선택)"},
                        "optional": True,
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "sheet_url_input",
                            "placeholder": {"type": "plain_text", "text": "https://docs.google.com/spreadsheets/d/..."}
                        }
                    },
                    {
                        "type": "input",
                        "block_id": "manual_phones_block",
                        "label": {"type": "plain_text", "text": "📱 직접 입력 (선택)"},
                        "optional": True,
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "manual_phones_input",
                            "multiline": True,
                            "placeholder": {"type": "plain_text", "text": "01012345678\n010-1234-5678\n여러 번호를 줄바꿈으로 구분"}
                        }
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": "💡 *Tip*: 구글 시트와 직접 입력을 동시에 사용하면 모든 번호가 합쳐집니다."
                            }
                        ]
                    },
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*3단계: 발송할 메시지 작성*\n수신자에게 전달할 메시지를 입력하세요."
                        }
                    },
                    {
                        "type": "input",
                        "block_id": "message_block",
                        "label": {"type": "plain_text", "text": "메시지 내용"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "message_input",
                            "multiline": True,
                            "initial_value": default_message,
                            "placeholder": {"type": "plain_text", "text": placeholder},
                            "max_length": 2000
                        }
                    }
                ]
            }
        )
        
    except Exception as e:
        print(f"Error in handle_type_selection: {str(e)}")
        import traceback
        print(traceback.format_exc())
        ack()

# 타입별 모달 제출 핸들러 (OT용) - 확인 모달로 이동
@app.view("google_sheet_ot_modal")
def handle_ot_submission(ack, body, client, view):
    handle_google_sheet_submission_to_confirmation(ack, body, client, view, "ot")

# 타입별 모달 제출 핸들러 (교육용) - 확인 모달로 이동
@app.view("google_sheet_education_modal")
def handle_education_submission(ack, body, client, view):
    handle_google_sheet_submission_to_confirmation(ack, body, client, view, "education")

# 타입별 모달 제출 핸들러 (장소/시간) - 확인 모달로 이동
@app.view("google_sheet_location_modal")
def handle_location_submission(ack, body, client, view):
    handle_google_sheet_submission_to_confirmation(ack, body, client, view, "location")

# 전화번호 선택 모달로 이동하는 핸들러
def handle_google_sheet_submission_to_confirmation(ack, body, client, view, message_type):
    try:
        metadata = json.loads(view.get('private_metadata', '{}'))
        user_id = metadata.get('user_id')
        channel_id = metadata.get('channel_id')
        
        # 권한 재확인
        if not is_user_allowed(user_id):
            ack()
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="❌ 이 봇을 사용할 권한이 없습니다."
            )
            return
        
        # 발신번호 가져오기
        sender_number = view['state']['values']['sender_number_block']['sender_number_select']['selected_option']['value']
        
        # 구글 시트 URL 가져오기 (선택사항)
        sheet_url = view['state']['values']['sheet_url_block']['sheet_url_input'].get('value', '')
        
        # 직접 입력한 전화번호 가져오기 (선택사항)
        manual_phones_text = view['state']['values']['manual_phones_block']['manual_phones_input'].get('value', '')
        
        # 메시지 가져오기
        message = view['state']['values']['message_block']['message_input']['value']
        
        if not message:
            ack(
                response_action="errors",
                errors={
                    "message_block": "발송할 메시지를 입력해주세요."
                }
            )
            return
        
        # 전화번호 수집
        phone_numbers = []
        error_messages = []
        sheet_phone_count = 0
        manual_phone_count = 0
        
        # 1. 구글 시트에서 전화번호 추출
        if sheet_url and sheet_url.strip():
            sheet_phones, sheet_error = extract_phone_numbers_from_google_sheet(sheet_url)
            if sheet_error:
                error_messages.append(f"구글 시트: {sheet_error}")
            elif sheet_phones:
                for phone in sheet_phones:
                    if phone not in phone_numbers:
                        phone_numbers.append(phone)
                        sheet_phone_count += 1
                print(f"Added {sheet_phone_count} phones from Google Sheet")
        
        # 2. 직접 입력한 전화번호 추출
        if manual_phones_text and manual_phones_text.strip():
            manual_phones = extract_phone_numbers_from_text(manual_phones_text)
            for phone in manual_phones:
                if phone not in phone_numbers:
                    phone_numbers.append(phone)
                    manual_phone_count += 1
            print(f"Added {manual_phone_count} phones from manual input")
        
        # 둘 다 입력하지 않은 경우
        if not sheet_url and not manual_phones_text:
            ack(
                response_action="errors",
                errors={
                    "sheet_url_block": "구글 시트 URL 또는 직접 입력 중 하나 이상을 입력해주세요."
                }
            )
            return
        
        # 전화번호를 찾지 못한 경우
        if not phone_numbers:
            error_msg = "전화번호를 찾을 수 없습니다."
            if error_messages:
                error_msg = " / ".join(error_messages)
            ack(
                response_action="errors",
                errors={
                    "sheet_url_block": error_msg
                }
            )
            return
        
        # 타입별 이모지
        type_emoji = {
            "ot": "🎓",
            "education": "📚",
            "location": "📍"
        }
        emoji = type_emoji.get(message_type, "📨")
        
        # 전화번호 체크박스 생성 (Slack 제한: 최대 10개 옵션)
        # 10개씩 나눠서 여러 체크박스 그룹으로 만들기
        
        # 전화번호 출처 정보 생성
        source_info_parts = []
        if sheet_phone_count > 0:
            source_info_parts.append(f"📊 구글 시트: {sheet_phone_count}개")
        if manual_phone_count > 0:
            source_info_parts.append(f"📱 직접 입력: {manual_phone_count}개")
        source_info = " / ".join(source_info_parts) if source_info_parts else ""
        
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} 수신자 선택"}
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*총 {len(phone_numbers)}개의 전화번호를 찾았습니다.*\n{source_info}\n\n✅ 문자를 보낼 번호를 선택하세요. (기본: 전체 선택)"
                }
            },
            {"type": "divider"}
        ]
        
        # 전화번호를 10개씩 묶어서 체크박스 생성
        for i in range(0, len(phone_numbers), 10):
            chunk = phone_numbers[i:i+10]
            options = []
            
            for phone in chunk:
                # 전화번호 포맷팅 (010-1234-5678)
                formatted = f"{phone[:3]}-{phone[3:7]}-{phone[7:]}"
                options.append({
                    "text": {"type": "plain_text", "text": formatted},
                    "value": phone
                })
            
            blocks.append({
                "type": "input",
                "block_id": f"phone_select_{i}",
                "label": {"type": "plain_text", "text": f"번호 목록 ({i+1}-{min(i+10, len(phone_numbers))})"},
                "optional": True,
                "element": {
                    "type": "checkboxes",
                    "action_id": f"select_phones_{i}",
                    "options": options,
                    "initial_options": options  # 기본으로 전체 선택
                }
            })
        
        # 전화번호 선택 모달로 push
        ack(
            response_action="push",
            view={
                "type": "modal",
                "callback_id": f"select_recipients_{message_type}",
                "private_metadata": json.dumps({
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "message_type": message_type,
                    "sender_number": sender_number,
                    "sheet_url": sheet_url,
                    "message": message,
                    "phone_numbers": phone_numbers
                }),
                "title": {"type": "plain_text", "text": "수신자 선택"},
                "submit": {"type": "plain_text", "text": "다음"},
                "close": {"type": "plain_text", "text": "취소"},
                "blocks": blocks
            }
        )
        
    except Exception as e:
        print(f"Error in handle_google_sheet_submission_to_confirmation: {str(e)}")
        import traceback
        print(traceback.format_exc())
        ack()

# 수신자 선택 모달 제출 핸들러 (OT)
@app.view("select_recipients_ot")
def handle_recipients_ot(ack, body, client, view):
    handle_recipients_selection(ack, body, client, view, "ot")

# 수신자 선택 모달 제출 핸들러 (교육)
@app.view("select_recipients_education")
def handle_recipients_education(ack, body, client, view):
    handle_recipients_selection(ack, body, client, view, "education")

# 수신자 선택 모달 제출 핸들러 (장소/시간)
@app.view("select_recipients_location")
def handle_recipients_location(ack, body, client, view):
    handle_recipients_selection(ack, body, client, view, "location")

# 수신자 선택 후 확인 모달로 이동
def handle_recipients_selection(ack, body, client, view, message_type):
    print(f"=== handle_recipients_selection called for {message_type} ===")
    try:
        metadata = json.loads(view.get('private_metadata', '{}'))
        user_id = metadata.get('user_id')
        channel_id = metadata.get('channel_id')
        message = metadata.get('message')
        sender_number = metadata.get('sender_number')
        all_phone_numbers = metadata.get('phone_numbers')
        
        print(f"User: {user_id}, Total phones: {len(all_phone_numbers) if all_phone_numbers else 0}")
        
        # 권한 재확인
        if not is_user_allowed(user_id):
            print(f"User {user_id} not allowed")
            ack()
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="❌ 이 봇을 사용할 권한이 없습니다."
            )
            return
        
        # 선택된 전화번호만 수집
        selected_phones = []
        values = view['state']['values']
        
        print(f"Checking view state, keys: {list(values.keys())}")
        
        for block_id, block_value in values.items():
            print(f"Processing block: {block_id}")
            if block_id.startswith('phone_select_'):
                for action_id, action_value in block_value.items():
                    print(f"  Action: {action_id}")
                    if action_id.startswith('select_phones_'):
                        selected = action_value.get('selected_options', [])
                        print(f"  Selected {len(selected)} options")
                        for option in selected:
                            selected_phones.append(option['value'])
        
        print(f"Total selected phones: {len(selected_phones)}")
        
        # 선택된 번호가 없으면 에러
        if not selected_phones:
            print("No phones selected, returning error")
            ack(
                response_action="errors",
                errors={
                    "phone_select_0": "최소 1명 이상의 수신자를 선택해야 합니다."
                }
            )
            return
        
        # 최종 발송 대상
        final_phone_numbers = selected_phones
        
        # 타입별 이모지
        type_emoji = {
            "ot": "🎓",
            "education": "📚",
            "location": "📍"
        }
        emoji = type_emoji.get(message_type, "📨")
        
        # 전화번호 목록 생성
        phone_list = '\n'.join([f"• {p[:3]}-{p[3:7]}-{p[7:]}" for p in final_phone_numbers[:30]])
        if len(final_phone_numbers) > 30:
            phone_list += f"\n... 외 {len(final_phone_numbers) - 30}개"
        
        # 제외된 번호 표시
        excluded_phones = [p for p in all_phone_numbers if p not in selected_phones]
        excluded_info = ""
        if excluded_phones:
            excluded_list = '\n'.join([f"• {p[:3]}-{p[3:7]}-{p[7:]}" for p in excluded_phones[:10]])
            if len(excluded_phones) > 10:
                excluded_list += f"\n... 외 {len(excluded_phones) - 10}개"
            excluded_info = f"\n\n*🚫 제외된 번호 ({len(excluded_phones)}개)*\n{excluded_list}"
        
        print(f"Preparing confirmation modal: {len(final_phone_numbers)} recipients, {len(excluded_phones)} excluded")
        print(f"Message length: {len(message)} chars")
        print(f"Message preview: {message[:100]}...")
        
        # 메시지가 너무 길면 잘라내기 (Slack 제한)
        display_message = message
        if len(message) > 3000:
            display_message = message[:3000] + "\n... (내용 생략)"
        
        # 발신번호 포맷팅
        formatted_sender = f"{sender_number[:3]}-{sender_number[3:7]}-{sender_number[7:]}"
        
        try:
            # 확인 모달로 update (push 대신 - Slack 3단계 제한 회피)
            ack(
                response_action="update",
                view={
                    "type": "modal",
                    "callback_id": f"confirm_send_{message_type}",
                    "private_metadata": json.dumps({
                        "user_id": user_id,
                        "channel_id": channel_id,
                        "message_type": message_type,
                        "sender_number": sender_number,
                        "message": message,
                        "phone_numbers": final_phone_numbers
                    }),
                    "title": {"type": "plain_text", "text": "발송 확인"},
                    "submit": {"type": "plain_text", "text": "✅ 발송"},
                    "close": {"type": "plain_text", "text": "❌ 취소"},
                    "blocks": [
                        {
                            "type": "header",
                            "text": {"type": "plain_text", "text": f"{emoji} 문자를 발송하시겠습니까?"}
                        },
                        {"type": "divider"},
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*📞 발신번호*\n{formatted_sender}"
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*📊 발송 대상*\n총 *{len(final_phone_numbers)}명*에게 발송됩니다."
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*✅ 수신자 목록*\n{phone_list}{excluded_info}"
                            }
                        },
                        {"type": "divider"},
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "*📝 발송 메시지*"
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"```{display_message}```"
                            }
                        },
                        {"type": "divider"},
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": "⚠️ 발송 후에는 취소할 수 없습니다. 내용을 다시 한 번 확인해주세요."
                                }
                            ]
                        }
                    ]
                }
            )
            print("Confirmation modal pushed successfully")
        except Exception as modal_error:
            print(f"Error creating confirmation modal: {str(modal_error)}")
            import traceback
            print(traceback.format_exc())
            ack()
        
    except Exception as e:
        print(f"Error in handle_recipients_selection: {str(e)}")
        import traceback
        print(traceback.format_exc())
        ack()

# 확인 모달에서 발송 버튼 클릭 (OT)
@app.view("confirm_send_ot")
def handle_confirm_ot(ack, body, client, view):
    handle_final_send(ack, body, client, view, "ot")

# 확인 모달에서 발송 버튼 클릭 (교육)
@app.view("confirm_send_education")
def handle_confirm_education(ack, body, client, view):
    handle_final_send(ack, body, client, view, "education")

# 확인 모달에서 발송 버튼 클릭 (장소/시간)
@app.view("confirm_send_location")
def handle_confirm_location(ack, body, client, view):
    handle_final_send(ack, body, client, view, "location")

# 최종 발송 핸들러
def handle_final_send(ack, body, client, view, message_type):
    # 모든 모달 닫기
    ack(response_action="clear")
    
    try:
        metadata = json.loads(view.get('private_metadata', '{}'))
        user_id = metadata.get('user_id')
        channel_id = metadata.get('channel_id')
        message = metadata.get('message')
        phone_numbers = metadata.get('phone_numbers')
        sender_number = metadata.get('sender_number')
        
        # 권한 재확인
        if not is_user_allowed(user_id):
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="❌ 이 봇을 사용할 권한이 없습니다."
            )
            return
        
        # 발신번호 포맷팅
        formatted_sender = f"{sender_number[:3]}-{sender_number[3:7]}-{sender_number[7:]}" if sender_number else "미지정"
        
        # 발송 중 메시지
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"📤 {len(phone_numbers)}명에게 문자 발송 중... (발신: {formatted_sender})"
        )
        
        # SMS 발송
        result = send_sms_via_solapi(phone_numbers, message, sender_number)
        
        # 에러 체크
        if not result:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"❌ 문자 발송 실패: 솔라피 API 응답 없음"
            )
            return
        
        if result.get('error'):
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"❌ 문자 발송 실패: {result.get('error')}"
            )
            return
        
        # 솔라피 API v4 응답 체크
        status = result.get('status')
        error_code = result.get('errorCode')
        
        # 에러가 있는 경우
        if error_code:
            error_msg = result.get('errorMessage', '알 수 없는 오류')
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"❌ 문자 발송 실패\n• 에러 코드: {error_code}\n• 오류: {error_msg}"
            )
            return
        
        # 정상 발송된 경우
        if status in ['SENDING', 'COMPLETE', 'PENDING']:
            count = result.get('count', {})
            total = count.get('total', 0)
            success = count.get('registeredSuccess', 0)
            failed = count.get('registeredFailed', 0)
            
            balance = result.get('balance', {})
            cost = balance.get('sum', 0)
            
            # ========== DynamoDB에 발송 기록 저장 ==========
            save_result = save_sms_history_to_dynamodb(
                user_id=user_id,
                message_type=message_type,
                message=message,
                phone_numbers=phone_numbers,
                result=result
            )
            
            db_status = "✅ 기록 저장됨" if save_result else "⚠️ 기록 저장 실패"
            # ================================================
            
            # 타입별 이모지
            type_emoji = {
                "ot": "🎓",
                "education": "📚",
                "location": "📍"
            }
            emoji = type_emoji.get(message_type, "📨")
            
            # 전화번호 목록 (최대 10개만 표시)
            phone_list = '\n'.join([f"• {phone}" for phone in phone_numbers[:10]])
            if len(phone_numbers) > 10:
                phone_list += f"\n... 외 {len(phone_numbers) - 10}개"
            
            # 메시지 제목 추출
            title = extract_message_title(message)
            
            # 한국 시간
            now_kst = datetime.now(KST)
            send_time_str = now_kst.strftime('%Y-%m-%d %H:%M:%S')
            
            client.chat_postMessage(
                channel=channel_id,
                text=f"{emoji} *문자 발송 완료*\n\n*📋 교육명*\n{title}\n\n*📞 발신번호*\n{formatted_sender}\n\n*🕐 발송 시간*\n{send_time_str} (KST)\n\n*발송 결과*\n• 상태: {status}\n• 전체: {total}건\n• 성공: {success}건\n• 실패: {failed}건\n• 비용: {cost}원\n• DB: {db_status}\n\n*메시지*\n```{message}```\n\n*수신자*\n{phone_list}"
            )
        else:
            # 알 수 없는 상태
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"⚠️ 알 수 없는 상태: {status}\n전체 응답: {json.dumps(result, ensure_ascii=False)}"
            )
        
    except Exception as e:
        print(f"Error in handle_final_send: {str(e)}")
        import traceback
        print(traceback.format_exc())
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"❌ 처리 중 오류가 발생했습니다: {str(e)}"
        )

# Lambda 핸들러
def lambda_handler(event, context):
    slack_handler = SlackRequestHandler(app=app)
    return slack_handler.handle(event, context)
