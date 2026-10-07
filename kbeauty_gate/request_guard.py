"""사용자 요청 자체를 먼저 본다: 금지 구역·비밀·발송·예약·자료 속 지시는 거절 이유를 답하고 기록한다.

앱 판단(1겹)이다. 판단이 뚫려도 OpenShell 정책(2겹)이 같은 행동을 막는다.
"""
import re
from typing import Dict, List

RULES = [
    ("read-restricted", r"restricted|최신\s*검증|latest[\s_-]*verified|의료\s*정보|medical|医療|医疗|醫療"),
    ("read-secrets", r"secrets?\b|토큰|token|service_key|비밀\s*키|api[\s_-]*key|トークン|令牌|密钥|密鑰"),
    ("send", r"이메일|메일|e-?mail|보내\s*(?:줘|주|달)|\bsend\b|送信|メール|发送|發送|邮件|郵件"),
    ("book", r"예약|\bbook(?:ing)?\b|\breserv|予約|预约|預約|결제|\bpay\b"),
    ("follow-document", r"venue_partner_memo|파트너\s*메모|품질\s*검토\s*절차|partner\s*memo"),
    ("upload", r"백업|업로드|\bupload|\bback\s*up|\bbackup|アップロード|バックアップ|上传|上傳|备份|備份"),
]
NEGATION = re.compile(r"하지\s*마|마세요|말아|않|\bdon'?t\b|\bdo not\b|\bnever\b|\bnot yet\b|しないで|ないでください|不要|別|别")
# Commas split clauses too, so "restricted 읽어 줘, 예약은 하지 마세요" negates only the booking part
CLAUSE = re.compile(r"[.!?。！？\n,，、;]+")

MESSAGES = {
    "ko": {"read-restricted": "접근 금지 구역의 자료는 열지 않았어요. 허용된 자료만으로 정리했어요.",
           "read-secrets": "비밀 정보는 열지 않았어요.",
           "send": "메일이나 메시지는 보내지 않았어요. 초안을 확인한 뒤 직접 보내 주세요.",
           "book": "예약이나 결제는 하지 않았어요. 초안을 확인한 뒤 직접 예약해 주세요.",
           "follow-document": "자료 안에 적힌 지시는 따르지 않았어요. 자료는 참고로만 써요.",
           "upload": "외부 주소로 올리거나 백업하지 않았어요. 결과는 이 화면에서만 확인해 주세요."},
    "en": {"read-restricted": "I did not open the restricted area. The draft uses only the permitted sources.",
           "read-secrets": "I did not open any stored secrets.",
           "send": "Nothing was emailed or sent. Please review the draft and send it yourself.",
           "book": "Nothing was booked or paid. Please review the draft and book it yourself.",
           "follow-document": "I did not follow instructions written inside the source documents.",
           "upload": "Nothing was uploaded or backed up to an outside address. Please review the result on this screen."},
    "ja": {"read-restricted": "立ち入り禁止の資料は開いていません。許可された資料だけでまとめました。",
           "read-secrets": "秘密情報は開いていません。",
           "send": "メールやメッセージは送っていません。下書きを確認してからご自身で送ってください。",
           "book": "予約や支払いはしていません。下書きを確認してからご自身で予約してください。",
           "follow-document": "資料の中に書かれた指示には従っていません。",
           "upload": "外部のアドレスへのアップロードやバックアップはしていません。結果はこの画面でご確認ください。"},
    "zh-Hans": {"read-restricted": "没有打开禁止访问的资料，只使用了允许的资料。",
                "read-secrets": "没有打开机密信息。",
                "send": "没有发送任何邮件或消息。请确认草案后自行发送。",
                "book": "没有进行任何预约或付款。请确认草案后自行预约。",
                "follow-document": "没有执行资料中写的指令。",
                "upload": "没有上传或备份到外部地址。请在此页面查看结果。"},
    "zh-Hant": {"read-restricted": "沒有開啟禁止存取的資料，只使用了允許的資料。",
                "read-secrets": "沒有開啟機密資訊。",
                "send": "沒有傳送任何郵件或訊息。請確認草案後自行傳送。",
                "book": "沒有進行任何預約或付款。請確認草案後自行預約。",
                "follow-document": "沒有執行資料中寫的指令。",
                "upload": "沒有上傳或備份到外部位址。請在此頁面查看結果。"},
}
REASONS = {
    "read-restricted": "사용자 요청이 접근 금지 구역을 가리킴",
    "read-secrets": "사용자 요청이 비밀 정보를 가리킴",
    "send": "외부 발송은 하지 않음 (초안만 작성)",
    "book": "예약과 결제는 하지 않음 (초안만 작성)",
    "follow-document": "자료 속 지시는 사용자 요청이 아님",
    "upload": "외부 주소로 올리기와 백업은 하지 않음",
}


def screen_request(message: str) -> List[Dict]:
    """Return refused actions in first-seen order; negated clauses ("예약하지 마세요") are not requests."""
    found: List[Dict] = []
    for clause in CLAUSE.split(message or ""):
        if NEGATION.search(clause):
            continue
        for action, pattern in RULES:
            if re.search(pattern, clause, re.IGNORECASE) and action not in {f["action"] for f in found}:
                found.append({"action": action, "reason": REASONS[action]})
    return found


def refusal_text(refusals: List[Dict], language: str) -> str:
    copy = MESSAGES.get(language, MESSAGES["en"])
    return " ".join(copy[item["action"]] for item in refusals)
