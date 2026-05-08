#!/usr/bin/env python3
"""
OpenAPI enrichment for Payven Mintlify docs.

Backend tarafında OpenAPI metadata'sı yetersiz: operationId, summary,
description, tag x-displayName eksik; text/plain content-type öneriliyor;
internal/PCI-riskli endpoint'ler public spec'te. Bu script:

1. Her operasyona deterministik camelCase operationId verir.
2. Her operasyona Türkçe summary ve (gerekirse) açıklama ekler.
3. Tag listesine x-displayName ekler (sidebar Türkçe görünsün).
4. Public spec'ten internal endpoint'leri ve PCI-riskli endpoint'leri siler.
5. text/plain ve text/json content-type'larını siler.

Idempotenttir; mevcut summary/description/operationId varsa korunur.
Backend düzelene kadar kalıcı çözüm değil ama Mintlify tarafında hemen
10/10 kalitesinde sayfa başlıkları/URL slug'ları/sidebar etiketleri üretir.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS = [
    ROOT / "api-reference/sanal-pos/openapi.json",
    ROOT / "api-reference/transfer/openapi.json",
    ROOT / "api-reference/identity/openapi.json",
    ROOT / "api-reference/fraud/openapi.json",
]

# Public spec'ten çıkartılacak path'ler (regex). Internal endpoint'ler veya
# kart numarasını query'de kabul edip PCI-DSS Req 3.4 ihlali yaratanlar.
DROP_PATH_PATTERNS = [
    r"^/api/v1/internal/",
    r"^/api/v1/tenants/seed$",
    r"^/api/v1/transactions/generate-random$",
    r"^/api/v1/connector-error-codes/bulk$",
    r"^/api/v1/validation/encrypt-card$",
    r"^/api/v1/validation/decrypt-card$",
    r"^/api/v1/payments/3d/callback$",
    r"^/api/v1/lookups/bank-bins/import$",
]
DROP_TAGS = {
    "FraudCallback",
    "InternalLookups", "InternalMerchants", "InternalPermissions",
    "InternalTenantFeatures", "InternalFraud",
    "Tenants",
}

# Tag → sidebar Türkçe etiketi
TAG_DISPLAY = {
    # Sanal POS
    "Payments": "Ödemeler",
    "Refunds": "İadeler",
    "Transactions": "İşlemler",
    "Chargebacks": "Chargeback",
    "CancellationRequests": "İptal Talepleri",
    "CheckoutSessions": "Hosted Checkout",
    "Connectors": "Konnektörler",
    "ConnectorConfigurations": "Konnektör Konfigürasyonları",
    "ConnectorErrorCodes": "Konnektör Hata Kodları",
    "RoutingRules": "Yönlendirme Kuralları",
    "SimpleRoutingRules": "Basit Yönlendirme Kuralları",
    "Reconciliations": "Mutabakat",
    "Settlements": "Settlement",
    "MerchantBankProfiles": "Bayi Banka Profilleri",
    "Webhooks": "Webhook'lar",
    "ApiRequestLogs": "API İstek Kayıtları",
    "Dashboard": "Dashboard",
    "Health": "Sağlık",
    "Trace": "Trace",
    "TestCards": "Test Kartları",
    "Settings": "Ayarlar",
    "Validation": "Validasyon",
    # Transfer
    "Transfers": "Transferler",
    "RecurringTransfers": "Tekrarlayan Transferler",
    "Recipients": "Alıcılar",
    "ReceiverAccounts": "Alıcı Hesapları",
    "Accounts": "Hesaplar",
    "Banks": "Bankalar",
    "BankBins": "Banka BIN'leri",
    "ConnectorAccounts": "Konnektör Hesapları",
    "ConnectorAccountTransferRules": "Konnektör Hesap Transfer Kuralları",
    "Me": "Oturum",
    # Identity
    "Auth": "Kimlik Doğrulama",
    "Users": "Kullanıcılar",
    "Merchants": "Bayiler",
    "Lookups": "Lookup Servisleri",
    "Permissions": "İzinler",
    "TenantApiKeys": "API Anahtarları",
    "TenantRoles": "Roller",
    "PlatformFeatures": "Platform Özellikleri",
    "PlatformPlans": "Platform Planları",
    "PlatformTenants": "Platform Tenant'lar",
    "PlatformTenantApiKeys": "Platform Tenant API Anahtarları",
    # Fraud
    "TenantFraudAlerts": "Fraud Uyarıları",
    "TenantFraudBlacklist": "Kara Liste",
    "TenantFraudLogs": "Fraud Logları",
    "TenantFraudMerchantPolicies": "Bayi Fraud Politikaları",
    "TenantFraudRules": "Fraud Kuralları",
    "PlatformFraudAlerts": "Platform Fraud Uyarıları",
    "PlatformFraudBlacklist": "Platform Kara Liste",
    "PlatformFraudRules": "Platform Fraud Kuralları",
}

# Tag → (tekil_TR, çoğul_TR, tekil_akuzatif, çoğul_akuzatif)
# Türkçe akuzatif eki: ünlü uyumuna göre -ı/-i/-u/-ü; ünlüyle bitiyorsa
# arada -y- kaynağı eklenir.
RESOURCE_TR = {
    "Payments":                    ("ödeme", "ödemeler", "ödemeyi", "ödemeleri"),
    "Refunds":                     ("iade", "iadeler", "iadeyi", "iadeleri"),
    "Transactions":                ("işlem", "işlemler", "işlemi", "işlemleri"),
    "Chargebacks":                 ("chargeback", "chargeback'ler", "chargeback'i", "chargeback'leri"),
    "CancellationRequests":        ("iptal talebi", "iptal talepleri", "iptal talebini", "iptal taleplerini"),
    "CheckoutSessions":            ("checkout oturumu", "checkout oturumları", "checkout oturumunu", "checkout oturumlarını"),
    "Connectors":                  ("konnektör", "konnektörler", "konnektörü", "konnektörleri"),
    "ConnectorConfigurations":     ("konnektör konfigürasyonu", "konnektör konfigürasyonları", "konnektör konfigürasyonunu", "konnektör konfigürasyonlarını"),
    "ConnectorErrorCodes":         ("konnektör hata kodu", "konnektör hata kodları", "konnektör hata kodunu", "konnektör hata kodlarını"),
    "RoutingRules":                ("yönlendirme kuralı", "yönlendirme kuralları", "yönlendirme kuralını", "yönlendirme kurallarını"),
    "SimpleRoutingRules":          ("basit yönlendirme kuralı", "basit yönlendirme kuralları", "basit yönlendirme kuralını", "basit yönlendirme kurallarını"),
    "Reconciliations":             ("mutabakat", "mutabakatlar", "mutabakatı", "mutabakatları"),
    "Settlements":                 ("settlement", "settlement'lar", "settlement'ı", "settlement'ları"),
    "MerchantBankProfiles":        ("bayi banka profili", "bayi banka profilleri", "bayi banka profilini", "bayi banka profillerini"),
    "Webhooks":                    ("webhook", "webhook'lar", "webhook'u", "webhook'ları"),
    "ApiRequestLogs":              ("API istek kaydı", "API istek kayıtları", "API istek kaydını", "API istek kayıtlarını"),
    "Dashboard":                   ("dashboard özeti", "dashboard özetleri", "dashboard özetini", "dashboard özetlerini"),
    "Health":                      ("sağlık durumu", "sağlık durumları", "sağlık durumunu", "sağlık durumlarını"),
    "Trace":                       ("trace", "trace'ler", "trace'i", "trace'leri"),
    "TestCards":                   ("test kartı", "test kartları", "test kartını", "test kartlarını"),
    "Settings":                    ("ayar", "ayarlar", "ayarı", "ayarları"),
    "Validation":                  ("validasyon", "validasyonlar", "validasyonu", "validasyonları"),
    # Transfer
    "Transfers":                   ("transfer", "transferler", "transferi", "transferleri"),
    "RecurringTransfers":          ("tekrarlayan transfer", "tekrarlayan transferler", "tekrarlayan transferi", "tekrarlayan transferleri"),
    "Recipients":                  ("alıcı", "alıcılar", "alıcıyı", "alıcıları"),
    "ReceiverAccounts":            ("alıcı hesabı", "alıcı hesapları", "alıcı hesabını", "alıcı hesaplarını"),
    "Accounts":                    ("hesap", "hesaplar", "hesabı", "hesapları"),
    "Banks":                       ("banka", "bankalar", "bankayı", "bankaları"),
    "BankBins":                    ("banka BIN'i", "banka BIN'leri", "banka BIN'ini", "banka BIN'lerini"),
    "ConnectorAccounts":           ("konnektör hesabı", "konnektör hesapları", "konnektör hesabını", "konnektör hesaplarını"),
    "ConnectorAccountTransferRules": ("konnektör hesap transfer kuralı", "konnektör hesap transfer kuralları", "konnektör hesap transfer kuralını", "konnektör hesap transfer kurallarını"),
    "Me":                          ("oturum bilgisi", "oturum bilgileri", "oturum bilgisini", "oturum bilgilerini"),
    # Identity
    "Auth":                        ("kimlik doğrulama", "kimlik doğrulama işlemleri", "kimlik doğrulamayı", "kimlik doğrulama işlemlerini"),
    "Users":                       ("kullanıcı", "kullanıcılar", "kullanıcıyı", "kullanıcıları"),
    "Merchants":                   ("bayi", "bayiler", "bayiyi", "bayileri"),
    "Lookups":                     ("lookup kaydı", "lookup kayıtları", "lookup kaydını", "lookup kayıtlarını"),
    "Permissions":                 ("izin", "izinler", "izni", "izinleri"),
    "TenantApiKeys":               ("API anahtarı", "API anahtarları", "API anahtarını", "API anahtarlarını"),
    "TenantRoles":                 ("rol", "roller", "rolü", "rolleri"),
    "PlatformFeatures":            ("platform özelliği", "platform özellikleri", "platform özelliğini", "platform özelliklerini"),
    "PlatformPlans":               ("platform planı", "platform planları", "platform planını", "platform planlarını"),
    "PlatformTenants":             ("platform tenant", "platform tenant'lar", "platform tenant'ı", "platform tenant'ları"),
    "PlatformTenantApiKeys":       ("tenant API anahtarı", "tenant API anahtarları", "tenant API anahtarını", "tenant API anahtarlarını"),
    # Fraud
    "TenantFraudAlerts":           ("fraud uyarısı", "fraud uyarıları", "fraud uyarısını", "fraud uyarılarını"),
    "TenantFraudBlacklist":        ("kara liste kaydı", "kara liste kayıtları", "kara liste kaydını", "kara liste kayıtlarını"),
    "TenantFraudLogs":             ("fraud log kaydı", "fraud log kayıtları", "fraud log kaydını", "fraud log kayıtlarını"),
    "TenantFraudMerchantPolicies": ("bayi fraud politikası", "bayi fraud politikaları", "bayi fraud politikasını", "bayi fraud politikalarını"),
    "TenantFraudRules":            ("fraud kuralı", "fraud kuralları", "fraud kuralını", "fraud kurallarını"),
    "PlatformFraudAlerts":         ("platform fraud uyarısı", "platform fraud uyarıları", "platform fraud uyarısını", "platform fraud uyarılarını"),
    "PlatformFraudBlacklist":      ("platform kara liste kaydı", "platform kara liste kayıtları", "platform kara liste kaydını", "platform kara liste kayıtlarını"),
    "PlatformFraudRules":          ("platform fraud kuralı", "platform fraud kuralları", "platform fraud kuralını", "platform fraud kurallarını"),
}

PARAM_RE = re.compile(r"\{[^}]+\}")


def is_param(seg: str) -> bool:
    return seg.startswith("{") and seg.endswith("}")


def kebab_to_pascal(s: str) -> str:
    parts = re.split(r"[-_]", s)
    return "".join(p.title() for p in parts)


def derive_resource_pascal(tag: str) -> str:
    """Convert tag to singular Pascal: 'Payments' -> 'Payment', 'Bayiler'->stays."""
    if tag.endswith("ies"):
        return tag[:-3] + "y"
    if tag.endswith("ses"):
        return tag[:-2]  # Addresses->Address
    if tag.endswith("s") and not tag.endswith("ss"):
        return tag[:-1]
    return tag


def plural_pascal(tag: str) -> str:
    return tag


def path_segments(p: str) -> list[str]:
    parts = [s for s in p.split("/") if s]
    if parts[:2] == ["api", "v1"]:
        parts = parts[2:]
    return parts


def cap(s: str) -> str:
    return s[0].upper() + s[1:] if s else s


def make_op_id_and_summary(path: str, method: str, tag: str) -> tuple[str, str, str]:
    """Returns (operationId, summary_tr, description_tr). Honor accusative case."""
    segs = path_segments(path)
    method_l = method.lower()
    sing, plural, sing_acc, plural_acc = RESOURCE_TR.get(
        tag, (tag.lower(), tag.lower(), tag.lower(), tag.lower())
    )
    R = derive_resource_pascal(tag)
    Rp = plural_pascal(tag)

    # 3DS özel akış
    if path == "/api/v1/payments/3d/init":
        return ("initThreeDsPayment", "3D Secure ödemesini başlat",
                "3D Secure akışını başlatır; banka HTML formunu döner.")
    if path == "/api/v1/payments/3d/complete":
        return ("completeThreeDsPayment", "3D Secure ödemesini tamamla",
                "Banka callback'i sonrasında otorizasyonu tamamlar.")
    if path == "/api/v1/payments/3d/callback":
        return ("threeDsCallback", "3DS banka callback'i",
                "Banka tarafından çağrılan callback. Public API tüketicileri çağırmaz.")

    # /payments/recurring (non-id)
    if path == "/api/v1/payments/recurring":
        return ("createRecurringPayment", "Saved card ile tekrarlayan ödeme başlat", "")

    # /payments/{id}/recurring/cancel
    if path.endswith("/recurring/cancel"):
        return ("cancelRecurringPayment", "Tekrarlayan ödeme aboneliğini iptal et", "")

    # /payments/order-link
    if path == "/api/v1/payments/order-link":
        return ("createOrderLink", "Pay-by-link ödeme linki oluştur", "")

    # Bulk transfer aksiyonları
    if path.startswith("/api/v1/transfers/bulk/"):
        action = segs[-1]
        bulk = {
            "create":  ("bulkCreateTransfers",  "Toplu transfer paketi oluştur"),
            "approve": ("bulkApproveTransfers", "Toplu transfer paketini onayla"),
            "reject":  ("bulkRejectTransfers",  "Toplu transfer paketini reddet"),
            "send":    ("bulkSendTransfers",    "Toplu transfer paketini gönder"),
        }
        if action in bulk:
            op_id, summary = bulk[action]
            return op_id, summary, "Para Transferi 4-eyes akışının bir aşaması."

    # by-X filtreleri
    by_seg = next((s for s in segs if s.startswith("by-")), None)
    if by_seg:
        suffix = by_seg[3:]
        op_id = f"list{Rp}By{kebab_to_pascal(suffix)}"
        suffix_tr = {
            "bank": "bankaya göre",
            "saved-account": "kayıtlı hesaba göre",
            "connector": "konnektöre göre",
            "connector-configuration": "konnektör konfigürasyonuna göre",
            "tenant": "tenant'a göre",
        }.get(suffix, f"{suffix}'a göre")
        return op_id, f"{cap(plural_acc)} listele ({suffix_tr})", ""

    # Son non-param segment
    last_action: str | None = None
    for s in reversed(segs):
        if not is_param(s):
            last_action = s
            break

    last_seg = segs[-1] if segs else ""
    last_is_param = is_param(last_seg)

    # health alt-yolları
    if path == "/api/v1/health":
        return ("getHealth", "Servis sağlık durumunu getir", "")
    if path == "/api/v1/health/live":
        return ("livenessProbe", "Liveness probe", "Container/orchestrator için canlılık kontrolü.")
    if path == "/api/v1/health/ready":
        return ("readinessProbe", "Readiness probe", "Container/orchestrator için hazır olma kontrolü.")
    if path == "/api/v1/health/connectors":
        return ("getConnectorsHealth", "Konnektörlerin sağlık durumunu listele", "")

    # Auth alt-yolları (çoğu özel naming)
    auth_specials = {
        "/api/v1/auth/{slug}/token":           ("issueToken",      "Client credentials ile token üret"),
        "/api/v1/auth/{slug}/refresh":         ("refreshToken",    "Refresh token ile access token yenile"),
        "/api/v1/auth/{slug}/login":           ("loginUser",       "Oturum aç"),
        "/api/v1/auth/{slug}/logout":          ("logoutUser",      "Oturumu kapat"),
        "/api/v1/auth/{slug}/me":              ("getAuthMe",       "Oturum sahibinin profilini getir"),
        "/api/v1/auth/{slug}/register":        ("registerTenant",  "Yeni tenant kaydet"),
        "/api/v1/auth/change-password":        ("changePassword",  "Şifre değiştir"),
        "/api/v1/auth/update-profile":         ("updateProfile",   "Profili güncelle"),
        "/api/v1/me":                          ("getMe",           "Oturum sahibini getir"),
        "/api/v1/me/plan":                     ("getMyPlan",       "Oturum sahibinin aktif planını getir"),
        "/api/v1/me/permissions":              ("getMyPermissions","Oturum sahibinin izinlerini listele"),
        "/api/v1/merchants/me":                ("getMyMerchant",   "Oturum sahibinin bayi bilgilerini getir"),
        "/api/v1/permissions/grants":          ("listPermissionGrants" if method_l == "get" else "updatePermissionGrants",
                                                "İzin atamalarını listele" if method_l == "get" else "İzin atamalarını güncelle"),
        "/api/v1/users/roles":                 ("listUserRoles",   "Kullanıcı rollerini listele"),
        "/api/v1/dashboard/stats":             ("getDashboardStats","Dashboard istatistiklerini getir"),
        "/api/v1/dashboard/monthly":           ("getDashboardMonthly","Aylık dashboard özeti"),
        "/api/v1/dashboard/weekly":            ("getDashboardWeekly", "Haftalık dashboard özeti"),
        "/api/v1/dashboard/range":             ("getDashboardRange",  "Tarih aralığına göre dashboard özeti"),
        "/api/v1/dashboard":                   ("getDashboard",       "Dashboard özetini getir"),
        "/api/v1/accounts/transactions":       ("listAccountTransactions", "Hesap hareketlerini listele"),
        "/api/v1/connectoraccounts/bank-accounts": ("listConnectorBankAccounts", "Konnektör banka hesaplarını listele"),
        "/api/v1/webhooks/health":             ("getWebhookHealth", "Webhook sağlık durumunu getir"),
        "/api/v1/webhooks/transfer-notification": ("postTransferNotification", "Transfer bildirimi webhook'u"),
        "/api/v1/validation/iban":             ("validateIban", "IBAN doğrula"),
        "/api/v1/validation/card":             ("validateCard", "Kart numarası doğrula"),
        "/api/v1/validation/creditcard":       ("validateCreditCard", "Kredi kartı doğrula"),
    }
    if path in auth_specials:
        op_id, summary = auth_specials[path]
        return op_id, summary, ""

    # Sub-action haritası
    SUB_ACTION = {
        "activate":      ("activate",        f"{cap(sing_acc)} etkinleştir"),
        "deactivate":    ("deactivate",      f"{cap(sing_acc)} devre dışı bırak"),
        "approve":       ("approve",         f"{cap(sing_acc)} onayla"),
        "reject":        ("reject",          f"{cap(sing_acc)} reddet"),
        "cancel":        ("cancel",          f"{cap(sing_acc)} iptal et"),
        "pause":         ("pause",           f"{cap(sing_acc)} duraklat"),
        "resume":        ("resume",          f"{cap(sing_acc)} devam ettir"),
        "finalize":      ("finalize",        f"{cap(sing_acc)} sonuçlandır"),
        "complete":      ("complete",        f"{cap(sing_acc)} tamamla"),
        "capture":       ("capture",         f"Ön provizyondan çekim yap"),
        "refund":        ("refund",          f"{cap(sing_acc)} iade et"),
        "void":          ("void",            f"{cap(sing_acc)} iptal et (void)"),
        "query":         ("query",           f"{cap(sing_acc)} özet sorgula"),
        "history":       ("getHistory",      f"{cap(sing)} geçmişini getir"),
        "histories":     ("getHistory",      f"{cap(sing)} geçmişini getir"),
        "detail":        ("getDetail",       f"{cap(sing)} detaylı bilgisini getir"),
        "details":       ("listDetails",     f"{cap(sing)} detaylarını listele"),
        "health":        ("getHealth",       f"{cap(sing)} sağlık durumunu getir"),
        "stats":         ("getStats",        f"{cap(sing)} istatistiklerini getir"),
        "deliveries":    ("listDeliveries",  f"{cap(sing)} teslim geçmişini getir"),
        "rotate-secret": ("rotateSecret",    f"{cap(sing)} secret'ini yenile"),
        "reset-password":("resetPassword",   f"{cap(sing)} şifresini sıfırla"),
        "start":         ("start",           f"{cap(sing_acc)} başlat"),
        "score":         ("updateScore",     f"{cap(sing)} skorunu güncelle"),
        "settings":      None,  # özel: GET vs PUT
        "status":        ("updateStatus",    f"{cap(sing)} durumunu güncelle"),
        "generate":      ("generate",        f"Rastgele {sing} üret"),
        "import":        ("import",          f"{cap(plural_acc)} içe aktar"),
        "suspend":       ("suspend",         f"{cap(sing_acc)} askıya al"),
        "policy":        None,  # özel
        "plan":          None,  # özel: tenant plan vs me plan
        "payment-policy":("updatePaymentPolicy", f"{cap(sing)} ödeme politikasını güncelle"),
        "transaction-status": ("getTransactionStatus", "Hosted checkout işlem durumunu getir"),
        "point-inquiry": ("pointInquiry",    "Karta ait puan bakiyesini sorgula"),
        "pay":           ("pay",             "Hosted checkout oturumunda ödeme yap"),
        "resolve":       None,  # özel: detay resolve vs generic
        "bulk-resolve":  ("bulkResolveDetails", f"{cap(sing)} detaylarını topluca çözümle"),
        "bulk-delete":   ("bulkDelete",      f"{cap(plural_acc)} topluca sil"),
        "bulk-create":   ("bulkCreate",      f"{cap(plural_acc)} topluca oluştur"),
        "base-64":       ("getReceiptBase64","Transfer dekontunu base64 formatında getir"),
        "download":      ("downloadReceipt", "Transfer dekontunu indir"),
        "evaluate":      ("evaluate",        "Fraud risk skoru hesapla"),
    }

    # PATCH/GET on /policy (collection-level sub-resource)
    if last_action == "policy":
        if method_l == "get":
            return ("getMerchantFraudPolicy",   "Bayi fraud politikasını getir", "")
        if method_l in ("patch", "put"):
            return ("updateMerchantFraudPolicy","Bayi fraud politikasını güncelle", "")

    # /plan özel
    if last_action == "plan":
        # /me/plan zaten yukarıda yakalandı
        if path.endswith("/plan") and method_l == "put":
            return ("updateTenantPlan", "Tenant planını güncelle", "")

    # /settings özel — collection vs item
    if last_action == "settings":
        if method_l == "get":
            return (f"get{R}Settings", f"{cap(R)} ayarlarını getir", "")
        if method_l == "put":
            return (f"update{R}Settings", f"{cap(R)} ayarlarını güncelle", "")

    # /resolve özel
    if last_action == "resolve":
        if "details" in segs:
            return (f"resolve{R}Detail", f"{cap(sing_acc)} detayını çözümle", "")
        return (f"resolve{R}", f"{cap(sing_acc)} çözümle", "")

    # Genel sub-action eşlemesi
    if last_action in SUB_ACTION and SUB_ACTION[last_action] is not None:
        verb, summary = SUB_ACTION[last_action]
        # operationId: bazılarına özel naming
        special = {
            "rotate-secret":  f"rotate{R}Secret",
            "reset-password": f"reset{R}Password",
            "deliveries":     f"list{R}Deliveries",
            "history":        f"get{R}History",
            "histories":      f"get{R}History",
            "detail":         f"get{R}Detail",
            "details":        f"list{R}Details",
            "health":         f"get{R}Health",
            "score":          f"update{R}Score",
            "status":         f"update{R}Status",
            "generate":       f"generate{R}",
            "import":         f"import{Rp}",
            "stats":          f"get{R}Stats",
            "deliveries":     f"list{R}Deliveries",
            "bulk-delete":    f"bulkDelete{Rp}",
            "bulk-create":    f"bulkCreate{Rp}",
            "bulk-resolve":   f"bulkResolve{R}Details",
            "transaction-status": f"get{R}TransactionStatus",
            "point-inquiry":  f"point{R}Inquiry",
            "evaluate":       "evaluateFraud",
            "base-64":        f"get{R}ReceiptBase64",
            "download":       f"download{R}Receipt",
            "payment-policy": f"update{R}PaymentPolicy",
            "pay":            f"pay{R}",
        }
        op_id = special.get(last_action, f"{verb}{R}")
        return op_id, summary, ""

    # Genel CRUD
    if method_l == "get" and not last_is_param:
        return f"list{Rp}", f"{cap(plural_acc)} listele", ""
    if method_l == "get" and last_is_param:
        return f"get{R}", f"{cap(sing_acc)} getir", ""
    if method_l == "post" and not last_is_param:
        return f"create{R}", f"{cap(sing)} oluştur", ""
    if method_l == "put" and last_is_param:
        return f"update{R}", f"{cap(sing_acc)} güncelle", ""
    if method_l == "patch" and last_is_param:
        return f"patch{R}", f"{cap(sing_acc)} kısmi güncelle", ""
    if method_l == "delete" and last_is_param:
        return f"delete{R}", f"{cap(sing_acc)} sil", ""
    if method_l == "post" and last_is_param:
        return f"act{R}", f"{cap(sing_acc)} üzerinde işlem", ""

    return f"{method_l}{R}", f"{method_l.upper()} {R}", ""


def strip_unwanted_content_types(content: dict) -> dict:
    if not isinstance(content, dict):
        return content
    out = {}
    for ct, body in content.items():
        if ct in ("application/json", "application/problem+json", "multipart/form-data",
                  "application/x-www-form-urlencoded", "application/octet-stream", "application/pdf"):
            out[ct] = body
        elif ct in ("application/*+json", "text/plain", "text/json"):
            continue
        else:
            out[ct] = body
    return out


PROBLEM_DETAILS_SCHEMA = {
    "type": "object",
    "description": (
        "RFC 9457 — Problem Details for HTTP APIs. Tüm hata yanıtları bu zarfla döner; "
        "MIME tipi `application/problem+json`'dur. Programatik karar için `code` alanını, "
        "destek talebinde `correlation_id` alanını kullanın."
    ),
    "required": ["type", "title", "status", "code"],
    "properties": {
        "type": {
            "type": "string", "format": "uri",
            "description": "Hata tipinin kanonik URI'si (dokümantasyon linki olarak da çalışır).",
            "example": "https://docs.payven.com.tr/errors/bank_declined",
        },
        "title": {
            "type": "string",
            "description": "Kısa, insan-okur Türkçe başlık.",
            "example": "Banka işlemi reddetti",
        },
        "status": {
            "type": "integer", "format": "int32",
            "description": "HTTP status kodu (header ile aynı değer; gövdede yinelenir).",
            "example": 422,
        },
        "code": {
            "type": "string",
            "description": "Programatik hata kodu (snake_case). `type` URI'sinin son segmenti.",
            "example": "bank_declined",
        },
        "detail": {
            "type": "string", "nullable": True,
            "description": "Bu duruma ilişkin açıklayıcı mesaj.",
            "example": "Yetersiz bakiye (banka kodu: 51)",
        },
        "instance": {
            "type": "string", "nullable": True,
            "description": "Hatanın oluştuğu kaynak yolu.",
            "example": "/api/v1/payments",
        },
        "correlation_id": {
            "type": "string", "format": "uuid", "nullable": True,
            "description": "İstek zinciri kimliği. Yanıt header'ı `X-Correlation-Id` ile aynı değer. Destek talebinde paylaşın.",
            "example": "9f1c8e76-2a3b-4f12-9c8d-12cb24a8a8a8",
        },
        "errors": {
            "type": "array", "nullable": True,
            "description": "Validasyon hatalarında (`code: validation_failed`) alan-bazlı detay.",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "example": "card.number"},
                    "code":  {"type": "string", "example": "invalid_card"},
                    "message": {"type": "string", "example": "Kart numarası Luhn checksum'ı geçmiyor."},
                },
            },
        },
        "provider_error_code": {
            "type": "string", "nullable": True,
            "description": "Banka tarafının orijinal yanıt kodu (sadece `bank_declined` ailesinde dolar).",
            "example": "51",
        },
    },
}

# Mintlify "Try it" panelinde her endpoint'e aynı ortak hatalar uygulansın.
# components.responses altında referans olarak yaşar; her operasyona $ref ile bağlanır.
COMMON_RESPONSES = {
    "BadRequest": {
        "description": "Geçersiz istek (eksik alan, bozuk JSON).",
        "content": {"application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetails"},
            "example": {
                "type":   "https://docs.payven.com.tr/errors/bad_request",
                "title":  "Geçersiz istek",
                "status": 400, "code": "bad_request",
                "detail": "amount.amount alanı zorunlu.",
                "correlation_id": "9f1c8e76-2a3b-4f12-9c8d-12cb24a8a8a8",
            },
        }},
    },
    "Unauthorized": {
        "description": "`Authorization` header eksik, geçersiz veya süresi dolmuş.",
        "content": {"application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetails"},
            "example": {
                "type":   "https://docs.payven.com.tr/errors/invalid_token",
                "title":  "Geçersiz token", "status": 401, "code": "invalid_token",
                "detail": "Access token geçersiz veya süresi dolmuş — refresh edin.",
            },
        }},
    },
    "Forbidden": {
        "description": "Yetki yok, lisans yok veya merchant pasif.",
        "content": {"application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetails"},
            "example": {
                "type":   "https://docs.payven.com.tr/errors/forbidden",
                "title":  "Yetki yok", "status": 403, "code": "forbidden",
                "detail": "Bu rol bu kaynağı göremez.",
            },
        }},
    },
    "NotFound": {
        "description": "Kaynak bulunamadı.",
        "content": {"application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetails"},
            "example": {
                "type":   "https://docs.payven.com.tr/errors/resource_not_found",
                "title":  "Kaynak bulunamadı", "status": 404, "code": "resource_not_found",
            },
        }},
    },
    "Conflict": {
        "description": "Idempotency çakışması veya geçersiz durum geçişi.",
        "content": {"application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetails"},
            "example": {
                "type":   "https://docs.payven.com.tr/errors/idempotency_key_in_use",
                "title":  "Idempotency-Key çakışması",
                "status": 409, "code": "idempotency_key_in_use",
                "detail": "Bu Idempotency-Key daha önce farklı bir istek gövdesi ile kullanıldı.",
            },
        }},
    },
    "UnprocessableEntity": {
        "description": "Validasyon veya iş kuralı ihlali (`bank_declined`, `validation_failed`, `fraud_blocked` vb.).",
        "content": {"application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetails"},
            "example": {
                "type":   "https://docs.payven.com.tr/errors/bank_declined",
                "title":  "Banka işlemi reddetti",
                "status": 422, "code": "bank_declined",
                "detail": "Yetersiz bakiye (banka kodu: 51)",
                "provider_error_code": "51",
            },
        }},
    },
    "TooManyRequests": {
        "description": "Rate limit aşıldı. `Retry-After` header'ına uyun.",
        "headers": {
            "Retry-After": {
                "description": "Yeniden denemeden önce beklemeniz gereken saniye sayısı.",
                "schema": {"type": "integer"},
            },
        },
        "content": {"application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetails"},
            "example": {
                "type":   "https://docs.payven.com.tr/errors/rate_limit_exceeded",
                "title":  "İstek limiti aşıldı",
                "status": 429, "code": "rate_limit_exceeded",
            },
        }},
    },
    "ServerError": {
        "description": "Sunucu hatası. Exponential backoff ile tekrar deneyin (Idempotency-Key ile).",
        "content": {"application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetails"},
            "example": {
                "type":   "https://docs.payven.com.tr/errors/internal_server_error",
                "title":  "Sunucu hatası", "status": 500, "code": "internal_server_error",
            },
        }},
    },
    "ServiceUnavailable": {
        "description": "Hedef konnektör geçici olarak devre dışı (circuit breaker açık) veya bağımlılık servisi erişilemez.",
        "content": {"application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ProblemDetails"},
            "example": {
                "type":   "https://docs.payven.com.tr/errors/connector_unavailable",
                "title":  "Konnektör erişilemez",
                "status": 503, "code": "connector_unavailable",
            },
        }},
    },
}

# =====================================================================
# OPERATION_METADATA — top endpoint'lere zengin Türkçe açıklama
# Backend'de [EndpointDescription] / [SwaggerOperation(Description=)] ile
# kalıcı yapılana kadar buradan dolduruyoruz. Mintlify, OpenAPI
# operation.description'ı sayfanın üstünde lead olarak render eder.
# =====================================================================
OPERATION_METADATA: dict[tuple[str, str], dict[str, str]] = {
    # ----- Sanal POS — Ödemeler -----
    ("/api/v1/payments", "POST"): {
        "summary": "Ödeme oluştur",
        "description": (
            "Tek istekte Non-3D bir ödeme başlatır: kart bilgisi alınır, akıllı yönlendirme "
            "motoru uygun konnektörü seçer, banka onayı alınır ve sonuç döner.\n\n"
            "**Ne zaman kullanılır?** Düşük riskli B2B akışları, abonelik yenilemeleri "
            "(MIT — saved card ile) veya 3DS gerekmeyen kapalı devre senaryolar için.\n\n"
            "**Tüketici akışında [3D Secure](/sanal-pos/payments/3d-secure) önerilir** — "
            "chargeback sorumluluğu bankaya geçer. `Idempotency-Key` ile yeniden gönderim "
            "korumasını mutlaka kullanın."
        ),
    },
    ("/api/v1/payments/{transaction_id}", "GET"): {
        "summary": "Ödemeyi sorgula",
        "description": (
            "Bir ödemenin güncel durumunu, banka yanıt detayını ve işlem geçmişini döner. "
            "Webhook teslimi başarısız olduğunda sonucu doğrulamak için bu uç noktayı kullanın. "
            "Başarısız işlemler için yanıt `200 OK` döner ve `error_code` / `provider_error_code` "
            "alanları gövdede taşınır."
        ),
    },
    ("/api/v1/payments/{transaction_id}/refund", "POST"): {
        "summary": "Ödemeyi iade et",
        "description": (
            "Tamamlanmış bir ödemeyi tam veya kısmi olarak iade eder. "
            "Aynı işleme birden fazla kısmi iade yapılabilir (toplam orijinal tutarı aşamaz).\n\n"
            "**Idempotency-Key** kullanın — aynı tutarın iki kez iade edilmesini engeller. "
            "Önerilen pattern: `refund-{transaction_id}-{slot}`."
        ),
    },
    ("/api/v1/payments/{transaction_id}/void", "POST"): {
        "summary": "Ödemeyi iptal et (void)",
        "description": (
            "Mutabakat öncesi (gün sonu kapatılmadan) tam iptal yapar. Mutabakat sonrası bu "
            "uç nokta kullanılamaz; bunun yerine [iade](#refund-payment) yapın.\n\n"
            "Pre-Auth ile alınmış otorizasyonu bloke etmek için de bu uç nokta kullanılır "
            "(çekim yapılmadan rezervasyonun serbest bırakılması)."
        ),
    },
    ("/api/v1/payments/{transaction_id}/capture", "POST"): {
        "summary": "Ön provizyonu çekime dönüştür (capture)",
        "description": (
            "Daha önce `pre_auth` olarak alınmış bir otorizasyonu çekime dönüştürür. "
            "Çekim tutarı orijinal otorizasyondan **küçük veya eşit** olabilir; aşamaz."
        ),
    },
    ("/api/v1/payments/3d/init", "POST"): {
        "summary": "3D Secure ödemeyi başlat",
        "description": (
            "3DS akışını başlatır. Yanıtta gelen `redirect_url` ile müşteriyi bankanın 3DS "
            "sayfasına yönlendirin. Doğrulama sonrasında banka, başvuruda verdiğiniz "
            "`callback_url` adresine kullanıcıyı geri yönlendirir.\n\n"
            "Akış tamamlandıktan sonra otorizasyonu kesinleştirmek için "
            "[3D Secure tamamla](#complete-3ds) uç noktası çağrılır (otomatik veya manuel)."
        ),
    },
    ("/api/v1/payments/3d/complete", "POST"): {
        "summary": "3D Secure ödemeyi tamamla",
        "description": (
            "3DS doğrulamasından dönen kullanıcının `transaction_id`'si ile otorizasyonu "
            "tamamlar. Banka onayı alındığında işlem `completed` durumuna geçer; reddedilirse "
            "`failed` döner ve gövdede `error_code` / `provider_error_code` taşınır."
        ),
    },
    ("/api/v1/payments/order-link", "POST"): {
        "summary": "Pay-by-link oluştur",
        "description": (
            "Kart bilgisi almadan, müşteriye SMS / e-posta / WhatsApp ile paylaşılabilen "
            "bir ödeme linki üretir. Müşteri Payven Hosted Checkout sayfasında kart bilgisini "
            "girer (PCI-DSS SAQ A kapsamına uygun).\n\n"
            "Sonuç webhook ile gelir: `payment.completed` / `payment.failed`."
        ),
    },
    ("/api/v1/payments/recurring", "POST"): {
        "summary": "Tekrarlayan (recurring) ödeme al",
        "description": (
            "Daha önce kaydedilmiş bir kart token'ı ile yeni ödeme alır (Merchant-Initiated "
            "Transaction — MIT). 3DS akışı çalışmaz; chargeback sorumluluğu sizdedir.\n\n"
            "İlk işlemin (CIT — Customer-Initiated) **3DS ile** yapılmış olması, bankanın "
            "MIT serisini kabul etmesi için kritiktir. Bkz. [Subscription reçetesi](/recipes/subscription)."
        ),
    },
    ("/api/v1/payments/{transaction_id}/recurring/cancel", "POST"): {
        "summary": "Tekrarlayan ödemeyi iptal et",
        "description": (
            "Saklı kart token'ını iptal eder. Sonraki MIT denemesi `422 token_revoked` döner."
        ),
    },
    ("/api/v1/payments/{transaction_id}/history", "GET"): {
        "summary": "Ödeme geçmişini getir",
        "description": (
            "İşlemin durum değişimlerini kronolojik olarak döner: oluşturuldu → 3DS → "
            "otorize → tamamlandı / iade / iptal. Audit ve debug için kullanılır."
        ),
    },
    # ----- Sanal POS — Webhook'lar -----
    ("/api/v1/webhooks", "POST"): {
        "summary": "Webhook subscription oluştur",
        "description": (
            "Belirli olay tipleri için sizin endpoint'inize teslim alacağı bir abonelik kurar. "
            "Yanıtta dönen `secret` değerini saklayın — gelen webhook'ların imzasını "
            "[HMAC-SHA256 ile doğrularken](/sanal-pos/webhooks/signature) bu secret'ı kullanırsınız.\n\n"
            "Mevcut olaylar: bkz. [Webhook Olay Kataloğu](/sanal-pos/webhooks/events)."
        ),
    },
    ("/api/v1/webhooks", "GET"): {
        "summary": "Webhook subscription'ları listele",
        "description": "Tenant'a tanımlı tüm webhook subscription'larını sayfalı olarak döner.",
    },
    ("/api/v1/webhooks/{id}/rotate-secret", "POST"): {
        "summary": "Webhook secret'ını rotate et",
        "description": (
            "Yeni bir secret üretir. **Eski secret 24 saat boyunca geçerli kalır** — bu sürede "
            "her iki secret ile imzalanmış istekler kabul edilir, böylece zero-downtime geçiş yaparsınız."
        ),
    },
    ("/api/v1/webhooks/{id}/deliveries", "GET"): {
        "summary": "Webhook teslim loglarını listele",
        "description": (
            "Sizin endpoint'inize yapılan webhook teslim denemelerini döner: HTTP status kodu, "
            "yanıt süresi, retry sayısı, payload ve imza header'ları. Webhook teslim debug'ı için kullanılır."
        ),
    },
    # ----- Sanal POS — Hosted Checkout -----
    ("/api/v1/checkout/sessions", "POST"): {
        "summary": "Hosted checkout oturumu başlat",
        "description": (
            "Kart bilgisi sizin sunucularınızdan geçmeyen bir ödeme oturumu oluşturur. "
            "Yanıttaki `checkout_url` adresine müşteriyi yönlendirin; ödeme tamamlandığında "
            "Payven `return_url`'inize geri yönlendirir ve webhook teslim eder.\n\n"
            "**PCI-DSS yükü düşük** — SAQ A kapsamı yeterlidir. Bkz. [PCI SAQ Eşleme](/documentation/security/pci-saq)."
        ),
    },
    # ----- Sanal POS — İptal Talepleri (4-eyes) -----
    ("/api/v1/cancellation-requests", "POST"): {
        "summary": "İptal talebi oluştur",
        "description": (
            "4-eyes (iki onaylı) iptal akışını başlatır: bir kullanıcı talep oluşturur, "
            "ikinci kullanıcı (farklı rolde) onaylar veya reddeder. "
            "Düşük yetkili rolleri iptal yapabilmeyi sağlamak için tasarlanmıştır."
        ),
    },
    ("/api/v1/cancellation-requests/{id}/approve", "POST"): {
        "summary": "İptal talebini onayla",
        "description": (
            "Onay yapan kullanıcı, talebi oluşturandan **farklı** olmalıdır. Aksi halde "
            "`422 four_eyes_violation` döner. Onay sonrası işlem otomatik olarak void edilir."
        ),
    },
    ("/api/v1/cancellation-requests/{id}/reject", "POST"): {
        "summary": "İptal talebini reddet",
        "description": "İptal talebini gerekçeyle reddeder. Reddedilen talep yeniden açılamaz.",
    },
    # ----- Para Transferi -----
    ("/api/v1/transfers/bulk/create", "POST"): {
        "summary": "Toplu transfer paketi oluştur",
        "description": (
            "Birden fazla transferi tek pakette oluşturur (paket başına en fazla 1000). "
            "Paket `pending_approval` durumunda başlar; ikinci kullanıcı onaylayana kadar "
            "bankaya gönderilmez. Bkz. [4-Eyes Transfer reçetesi](/recipes/four-eyes-transfer)."
        ),
    },
    ("/api/v1/transfers/bulk/approve", "POST"): {
        "summary": "Transfer paketini onayla",
        "description": (
            "Paketi `approved` durumuna geçirir. Onay yapan kullanıcı, paketi oluşturandan "
            "farklı olmalıdır (4-eyes ilkesi)."
        ),
    },
    ("/api/v1/transfers/bulk/send", "POST"): {
        "summary": "Onaylanmış paketi gönder",
        "description": (
            "Onaylanmış paketteki tüm transferleri bankaya gönderir. Her transfer bağımsız "
            "işlenir; biri başarısız olsa diğerleri devam eder. Sonuçlar webhook ile gelir."
        ),
    },
    # ----- Identity -----
    ("/api/v1/auth/{slug}/token", "POST"): {
        "summary": "Access token al",
        "description": (
            "OAuth 2.0 Client Credentials akışıyla yeni access token üretir.\n\n"
            "**Token cache'leyin** — her API çağrısında yeniden almayın. Identity'de rate "
            "limit vardır (token endpoint'i IP başına dakikada 10). Token expire olmadan "
            "[refresh](#issue-refresh-token) ile yenileyin.\n\n"
            "Detay: [Kimlik Doğrulama](/documentation/concepts/authentication)."
        ),
    },
    ("/api/v1/auth/{slug}/refresh", "POST"): {
        "summary": "Token'ı yenile",
        "description": (
            "Refresh token ile yeni bir access token alır. Refresh token rotasyonludur: "
            "her başarılı refresh'te yeni bir refresh token döner ve eskisi geçersizleşir."
        ),
    },
}


# =====================================================================
# SCHEMA_PROPERTY_METADATA — top schema'lar için per-property açıklama + örnek
# Mintlify request/response field'larını bu metadata ile zenginleştirilmiş gösterir
# (Stripe seviyesi: tip, zorunlu/opsiyonel, açıklama, örnek değer).
# =====================================================================
SCHEMA_PROPERTY_METADATA: dict[str, dict] = {
    "CreatePaymentRequest": {
        "description": "Non-3D ödeme veya pre-auth oluşturma isteği gövdesi.",
        "required": ["amount", "card", "installment"],
        "properties": {
            "external_id": {
                "description": "Sizin sisteminizdeki sipariş kimliği. İdeal olarak `Idempotency-Key` ile aynı seed'den üretin.",
                "example": "ORDER-1001",
            },
            "basket_id": {
                "description": "Sepet kimliği — raporlama ve mutabakat için.",
                "example": "BASKET-2026-001",
            },
            "amount": {
                "description": "İşlem tutarı ve para birimi. Tutar kuruş cinsindendir (15000 = ₺150,00).",
            },
            "installment": {
                "description": "Taksit sayısı. `1` = peşin. Banka & BIN desteği gereklidir; desteklenmeyen taksit `invalid_installment` ile reddedilir.",
                "example": 1,
            },
            "card": {
                "description": "Kart bilgileri — Luhn checksum geçerli olmalı, son kullanma tarihi gelecekte olmalı.",
            },
            "description": {
                "description": "İşlem açıklaması. Banka ekstresi açıklamasına yansıyabilir.",
                "example": "Sipariş ödemesi",
            },
            "buyer": {
                "description": "Müşteri bilgileri. `ip_address` fraud kuralları için kritiktir.",
            },
            "billing_address": {
                "description": "Fatura adresi. Bazı bankalar/3DS senaryoları için risk skoruna girer.",
            },
            "shipping_address": {
                "description": "Teslimat adresi. Fiziksel ürünlerde fraud sinyali olarak kullanılır.",
            },
            "basket_items": {
                "description": "Sepet kalemleri. 3DS 2.x mesajlaşmasında risk skoruna katkı sağlar.",
            },
            "operation_type": {
                "description": "`sale` (varsayılan, anında çekim) veya `pre_auth` (ön provizyon — sonradan `/capture` gerekir).",
                "example": "sale",
            },
            "extra_properties": {
                "description": "Konnektör-spesifik özel alanlar (advanced). Genelde boş bırakın.",
            },
        },
    },
    "PaymentAmountRequestDto": {
        "description": "Tutar nesnesi — kuruş cinsinden tam sayı + ISO 4217 para birimi.",
        "required": ["amount", "currency"],
        "properties": {
            "amount": {
                "description": "Tutar — **kuruş cinsinden tam sayı**. 1,00 ₺ → 100, 150,00 ₺ → 15000.",
                "example": 15000,
            },
            "currency": {
                "description": "ISO 4217 para birimi kodu. Şu an yalnızca `TRY` desteklenir.",
                "example": "TRY",
            },
        },
    },
    "PaymentBuyerRequestDto": {
        "description": "Müşteri bilgileri — fraud sinyalleri ve banka risk skoru için.",
        "properties": {
            "id": {
                "description": "Müşteri kimliğiniz. Aynı kimliğin tekrarlayan ödemeleri fraud kurallarında kullanılır.",
                "example": "cust-001",
            },
            "name": {"description": "Müşteri adı.", "example": "Ahmet"},
            "surname": {"description": "Müşteri soyadı.", "example": "Yılmaz"},
            "email": {
                "description": "Müşteri e-posta adresi. Bazı bankaların 3DS mesajlarında zorunludur.",
                "example": "musteri@example.com",
            },
            "phone": {
                "description": "Müşteri telefon numarası (E.164 formatında önerilir).",
                "example": "+905551112233",
            },
            "ip_address": {
                "description": "Müşterinin **gerçek** IP'si. Reverse proxy arkasındaysanız `X-Forwarded-For` header'dan alın. Fraud için kritik.",
                "example": "85.105.10.10",
            },
            "identity_number": {
                "description": "TC kimlik numarası. Yüksek tutarlı işlemlerde bazı bankalar zorunlu kılar.",
                "example": "12345678901",
            },
        },
    },
    "PaymentAddressRequestDto": {
        "description": "Adres bilgisi (fatura veya teslimat).",
        "properties": {
            "contact_name": {"description": "Adresteki kişinin adı.", "example": "Ahmet Yılmaz"},
            "city": {"description": "Şehir adı.", "example": "İstanbul"},
            "country": {"description": "ISO 3166-1 alpha-2 ülke kodu.", "example": "TR"},
            "address": {"description": "Sokak ve bina detayı.", "example": "Maslak Mh. ..."},
            "postal_code": {"description": "Posta kodu.", "example": "34485"},
        },
    },
    "PaymentBasketItemRequestDto": {
        "description": "Sepet kalemi.",
        "required": ["name", "price", "quantity"],
        "properties": {
            "id": {"description": "Kaleminizin kimliği.", "example": "SKU-001"},
            "name": {"description": "Kalem adı.", "example": "Kablosuz kulaklık"},
            "price": {
                "description": "Kalem birim fiyatı — kuruş cinsinden.",
                "example": 7500,
            },
            "quantity": {"description": "Adet.", "example": 2},
        },
    },
    "PaymentOperationResultDto": {
        "description": "Yazma operasyonlarından (`POST /payments`, `/refund`, `/void`, `/capture`) dönen sonuç.",
        "required": ["transaction_id"],
        "properties": {
            "transaction_id": {
                "description": "Payven tarafından atanan benzersiz işlem kimliği. Sorgulama / aksiyon endpoint'lerinde URL parametresi olarak kullanılır.",
                "example": "8e3f5c12-9a7b-4c8d-bc4e-2c963f66afa6",
            },
            "status": {
                "description": "İşlemin mevcut durumu: `pending`, `pending_3ds`, `authorized`, `completed`, `failed`, `voided`, `refunded`, `partially_refunded`.",
                "example": "completed",
            },
            "is_success": {
                "description": "Operasyon başarılı mı? **Geçiş döneminde tutuluyor — yeni kodlarda HTTP status kodunu konuşturun** (2xx başarı, 4xx/5xx hata).",
                "example": True,
            },
            "message": {"description": "İnsan-okur durum mesajı.", "example": "İşlem başarıyla tamamlandı"},
            "error_code": {
                "description": "Yalnızca başarısız işlemlerde dolar — Payven canonical hata kodu.",
                "example": "bank_declined",
            },
            "provider_error_code": {
                "description": "Yalnızca başarısız işlemlerde dolar — bankanın orijinal yanıt kodu.",
                "example": "51",
            },
            "extra_properties": {
                "description": "Banka-spesifik ek alanlar: `auth_code`, `host_reference`, `provider_transaction_id`, `processed_at` vb.",
            },
        },
    },
    "RefundTransactionRequest": {
        "description": "İade isteği gövdesi. Tam veya kısmi iade için kullanılır.",
        "required": ["amount"],
        "properties": {
            "transaction_id": {
                "description": "İade edilecek işlemin Payven kimliği. URL'deki path parametresi ile aynı olmalı.",
            },
            "amount": {
                "description": "İade tutarı — kuruş cinsinden. Orijinal işlemden **küçük veya eşit** olmalı.",
                "example": 5000,
            },
            "currency": {
                "description": "ISO 4217. Genelde orijinal işlemle aynı; varsayılan `TRY`.",
                "example": "TRY",
            },
            "reason": {
                "description": "İade sebebi (serbest metin, audit log'una düşer).",
                "example": "Müşteri talebi — ürün iadesi",
            },
            "reason_code": {
                "description": "Yapısal iade sebebi: `customer_request`, `duplicate`, `fraud`, `defective`, `other`.",
                "example": "customer_request",
            },
            "extra_properties": {
                "description": "Konnektör-spesifik özel alanlar.",
            },
        },
    },
    "VoidTransactionRequest": {
        "description": "İptal (void) isteği gövdesi.",
        "properties": {
            "transaction_id": {
                "description": "İptal edilecek işlemin Payven kimliği.",
            },
            "reason": {
                "description": "İptal sebebi (serbest metin, audit log'una düşer).",
                "example": "Stok yok — sipariş iptal",
            },
            "extra_properties": {"description": "Konnektör-spesifik özel alanlar."},
        },
    },
    "CaptureTransactionRequest": {
        "description": "Pre-Auth (ön provizyon) → çekim isteği.",
        "required": ["amount"],
        "properties": {
            "transaction_id": {"description": "Pre-Auth ile alınmış işlemin Payven kimliği."},
            "amount": {
                "description": "Çekim tutarı — kuruş cinsinden. Orijinal otorizasyondan **küçük veya eşit** olmalı.",
                "example": 14750,
            },
            "reason": {"description": "Açıklama (serbest metin)."},
            "extra_properties": {"description": "Konnektör-spesifik özel alanlar."},
        },
    },
    "Init3DRequest": {
        "description": "3D Secure ödeme başlatma isteği. CreatePaymentRequest ile aynı alanlara ek olarak callback/return/cancel URL'leri taşır.",
        "required": ["amount", "card", "installment", "callback_url"],
        "properties": {
            "external_id": {"description": "Sizin sipariş kimliğiniz.", "example": "ORDER-1001"},
            "basket_id": {"description": "Sepet kimliği.", "example": "BASKET-2026-001"},
            "amount": {"description": "İşlem tutarı (kuruş + currency)."},
            "installment": {"description": "Taksit sayısı. `1` = peşin.", "example": 1},
            "card": {"description": "Kart bilgileri."},
            "callback_url": {
                "description": "**Zorunlu**. 3DS doğrulaması sonrası bankanın kullanıcıyı geri yönlendireceği HTTPS URL'iniz. Buradan gelen `transaction_id` ile [`/payments/3d/complete`](#complete-3ds) çağrılır.",
                "example": "https://example.com/3ds/return",
            },
            "cancel_url": {
                "description": "Müşteri 3DS akışını iptal ederse yönlendirileceği URL.",
                "example": "https://example.com/checkout/cancel",
            },
            "return_url": {
                "description": "Sonuç sayfasına yönlendirme için (success/fail unified). `callback_url` farklı sebeple kullanılır.",
            },
            "operation_type": {
                "description": "`sale` (varsayılan) veya `pre_auth`.",
                "example": "sale",
            },
            "extra_properties": {"description": "Konnektör-spesifik özel alanlar."},
        },
    },
    "CreateCheckoutSessionRequest": {
        "description": "Hosted checkout oturum isteği. Müşteri kart bilgisini Payven sayfasında girer.",
        "required": ["amount", "currency"],
        "properties": {
            "merchant_name": {
                "description": "Hosted checkout sayfasında gösterilecek bayi adı.",
                "example": "Acme Online",
            },
            "amount": {
                "description": "İşlem tutarı — kuruş cinsinden.",
                "example": 15000,
            },
            "currency": {"description": "ISO 4217 para birimi.", "example": "TRY"},
            "allowed_installments": {
                "description": "Müşteriye sunulacak taksit seçenekleri (`[1, 3, 6]` gibi). Boş ise sadece peşin.",
            },
            "description": {"description": "Sayfada gösterilecek açıklama.", "example": "Sipariş ödemesi"},
            "external_id": {"description": "Sizin sipariş kimliğiniz.", "example": "ORDER-1001"},
            "basket_id": {"description": "Sepet kimliği.", "example": "BASKET-2026-001"},
            "customer_email": {
                "description": "Müşteri e-posta adresi (makbuz için).",
                "example": "musteri@example.com",
            },
        },
    },
    "CreateOrderLinkRequest": {
        "description": "Pay-by-link oluşturma isteği. SMS/e-posta ile paylaşılan ödeme linki üretir.",
        "required": ["amount", "currency"],
        "properties": {
            "amount": {"description": "Tutar — kuruş cinsinden.", "example": 15000},
            "currency": {"description": "ISO 4217 para birimi.", "example": "TRY"},
            "installment": {"description": "İzin verilen maksimum taksit.", "example": 6},
            "callback_url": {
                "description": "Ödeme tamamlandığında server-to-server callback için HTTPS URL'iniz.",
            },
            "return_url": {
                "description": "Müşterinin ödeme sonrası yönlendirileceği sayfa.",
            },
            "description": {"description": "Linkte gösterilecek açıklama.", "example": "Sipariş #1001"},
            "external_id": {"description": "Sizin sipariş kimliğiniz.", "example": "ORDER-1001"},
            "customer_email": {
                "description": "Müşteri e-postası.",
                "example": "musteri@example.com",
            },
        },
    },
}


# Hangi durum kodlarının hangi method-tipinde varsayılan ekleneceği.
# 5XX, 401, 429 her endpoint'te; 422 yazma operasyonlarında; 404 path'inde param varsa.
def default_error_responses(method: str, path: str, has_body: bool) -> dict:
    refs = {
        "401": {"$ref": "#/components/responses/Unauthorized"},
        "403": {"$ref": "#/components/responses/Forbidden"},
        "429": {"$ref": "#/components/responses/TooManyRequests"},
        "500": {"$ref": "#/components/responses/ServerError"},
        "503": {"$ref": "#/components/responses/ServiceUnavailable"},
    }
    if "{" in path:
        refs["404"] = {"$ref": "#/components/responses/NotFound"}
    if method.lower() in ("post", "put", "patch", "delete"):
        refs["400"] = {"$ref": "#/components/responses/BadRequest"}
        refs["409"] = {"$ref": "#/components/responses/Conflict"}
        refs["422"] = {"$ref": "#/components/responses/UnprocessableEntity"}
    return refs


# x-codeSamples şablonu — Mintlify Try-it panelinin yan sütununda gösterilir.
# Top operasyonlar için tanımlıyoruz; auto-fill via path+method match.
def code_samples_for(path: str, method: str, server_url: str) -> list[dict] | None:
    """Returns list of language samples for top endpoints. None if not in priority list."""
    method_u = method.upper()
    full_url = f"{server_url}{path}"
    # Path param yer tutucularina ornek deger ata
    full_url_demo = re.sub(r"\{[^}]+\}", "8e3f5c12-9a7b-4c8d-bc4e-2c963f66afa6", full_url)

    PRIORITY = {
        ("/api/v1/payments", "POST"): "create-payment",
        ("/api/v1/payments/{transaction_id}", "GET"): "get-payment",
        ("/api/v1/payments/{transaction_id}/refund", "POST"): "refund-payment",
        ("/api/v1/payments/{transaction_id}/void", "POST"): "void-payment",
        ("/api/v1/payments/{transaction_id}/capture", "POST"): "capture-payment",
        ("/api/v1/payments/3d/init", "POST"): "init-3ds",
        ("/api/v1/payments/3d/complete", "POST"): "complete-3ds",
        ("/api/v1/payments/order-link", "POST"): "create-order-link",
        ("/api/v1/payments/recurring", "POST"): "create-recurring-payment",
        ("/api/v1/checkout/sessions", "POST"): "create-checkout-session",
        ("/api/v1/webhooks", "POST"): "create-webhook",
        ("/api/v1/transfers/bulk/create", "POST"): "bulk-create-transfers",
        ("/api/v1/transfers/{id}", "GET"): "get-transfer",
        ("/api/v1/auth/{slug}/token", "POST"): "issue-token",
    }
    key = (path, method_u)
    if key not in PRIORITY:
        return None

    has_body = method_u in ("POST", "PUT", "PATCH")
    body_snippet_curl = ""
    body_snippet_node = ""
    body_snippet_py   = ""
    body_snippet_cs   = ""
    body_snippet_go   = ""
    body_snippet_php  = ""
    if has_body:
        body_snippet_curl = " \\\n  -d '{ ...payload... }'"
        body_snippet_node = ",\n    body: JSON.stringify({ /* payload */ })"
        body_snippet_py   = ",\n    json={ ... }"
        body_snippet_cs   = "\n// Content = JsonContent.Create(payload);"
        body_snippet_go   = "\n// req.Body = bytes.NewReader(payloadJSON)"
        body_snippet_php  = "\n  CURLOPT_POSTFIELDS => json_encode(\$payload),"

    auth_curl = '-H "Authorization: Bearer $PAYVEN_TOKEN"'
    idem_curl = ' \\\n  -H "Idempotency-Key: order-1001"' if has_body else ""

    samples = [
        {"lang": "curl", "label": "cURL", "source":
         f"curl -X {method_u} {full_url_demo} \\\n  {auth_curl}{idem_curl}{body_snippet_curl}"},
        {"lang": "javascript", "label": "Node.js", "source":
         f'const res = await fetch(\n  "{full_url_demo}",\n  {{\n    method: "{method_u}",\n    headers: {{\n      Authorization: `Bearer ${{accessToken}}`,'
         + ('\n      "Idempotency-Key": "order-1001",' if has_body else '')
         + f'\n      "Content-Type": "application/json",\n    }}{body_snippet_node},\n  }},\n);\nconst data = await res.json();'},
        {"lang": "python", "label": "Python", "source":
         f'import httpx\nres = httpx.{method.lower()}(\n    "{full_url_demo}",\n    headers={{\n        "Authorization": f"Bearer {{access_token}}",'
         + ('\n        "Idempotency-Key": "order-1001",' if has_body else '')
         + f'\n    }}{body_snippet_py},\n)\ndata = res.json()'},
        {"lang": "csharp", "label": "C#", "source":
         f'var req = new HttpRequestMessage(HttpMethod.{method_u.title()}, "{full_url_demo}");\n'
         f'req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", accessToken);'
         + ('\nreq.Headers.Add("Idempotency-Key", "order-1001");' if has_body else '')
         + f'{body_snippet_cs}\nvar resp = await http.SendAsync(req);'},
        {"lang": "go", "label": "Go", "source":
         f'req, _ := http.NewRequest("{method_u}", "{full_url_demo}", nil)\n'
         f'req.Header.Set("Authorization", "Bearer "+accessToken)'
         + ('\nreq.Header.Set("Idempotency-Key", "order-1001")' if has_body else '')
         + f'{body_snippet_go}\nresp, _ := http.DefaultClient.Do(req)'},
        {"lang": "php", "label": "PHP", "source":
         f'$ch = curl_init("{full_url_demo}");\ncurl_setopt_array($ch, [\n  CURLOPT_CUSTOMREQUEST => "{method_u}",\n  CURLOPT_RETURNTRANSFER => true,\n  CURLOPT_HTTPHEADER => [\n    "Authorization: Bearer $accessToken",'
         + ('\n    "Idempotency-Key: order-1001",' if has_body else '')
         + f'\n  ],{body_snippet_php}\n]);\n$data = json_decode(curl_exec($ch), true);'},
    ]
    return samples


def enrich_spec(spec: dict) -> tuple[dict, dict]:
    paths = spec.get("paths", {})
    new_paths = {}
    drop_re = [re.compile(p) for p in DROP_PATH_PATTERNS]
    stats = {"ops": 0, "added_op_id": 0, "added_summary": 0,
             "stripped_paths": 0, "stripped_content_types": 0,
             "tag_displays": 0, "stripped_tags": 0,
             "added_problem_schema": 0, "added_default_responses": 0,
             "added_code_samples": 0, "stripped_empty_tags": 0,
             "enriched_op_metadata": 0, "enriched_schema_props": 0}

    # components.schemas / components.responses
    spec.setdefault("components", {})
    spec["components"].setdefault("schemas", {})
    spec["components"].setdefault("responses", {})
    if "ProblemDetails" not in spec["components"]["schemas"]:
        spec["components"]["schemas"]["ProblemDetails"] = PROBLEM_DETAILS_SCHEMA
        stats["added_problem_schema"] = 1
    for name, body in COMMON_RESPONSES.items():
        if name not in spec["components"]["responses"]:
            spec["components"]["responses"][name] = body

    # Schema property metadata enrichment (top schemas için)
    schemas = spec["components"]["schemas"]
    for sch_name, sch_meta in SCHEMA_PROPERTY_METADATA.items():
        if sch_name not in schemas:
            continue
        sch = schemas[sch_name]
        # Schema-level description ve required listesi
        if sch_meta.get("description") and not sch.get("description"):
            sch["description"] = sch_meta["description"]
        if sch_meta.get("required") and not sch.get("required"):
            sch["required"] = sch_meta["required"]
        # Property-level description + example
        sch_props = sch.get("properties") or {}
        for prop_name, prop_meta in (sch_meta.get("properties") or {}).items():
            if prop_name not in sch_props:
                continue
            p = sch_props[prop_name]
            if prop_meta.get("description") and not p.get("description"):
                p["description"] = prop_meta["description"]
                stats["enriched_schema_props"] += 1
            if "example" in prop_meta and "example" not in p:
                p["example"] = prop_meta["example"]

    for path, ops in paths.items():
        if any(r.match(path) for r in drop_re):
            stats["stripped_paths"] += 1
            continue

        keep_ops = {}
        for method, op in ops.items():
            if method.lower() not in ("get","post","put","patch","delete","head","options"):
                keep_ops[method] = op
                continue
            tags = op.get("tags") or []
            if tags and all(t in DROP_TAGS for t in tags):
                stats["stripped_paths"] += 1
                continue
            tag = tags[0] if tags else "Default"
            stats["ops"] += 1

            op_id, summary, description = make_op_id_and_summary(path, method, tag)
            if not op.get("operationId"):
                op["operationId"] = op_id
                stats["added_op_id"] += 1

            # OPERATION_METADATA — top endpoint'ler için zengin Türkçe summary + description
            meta_key = (path, method.upper())
            override = OPERATION_METADATA.get(meta_key)
            if override:
                if override.get("summary"):
                    op["summary"] = override["summary"]
                if override.get("description"):
                    op["description"] = override["description"]
                stats["enriched_op_metadata"] += 1
            else:
                if not op.get("summary"):
                    op["summary"] = summary
                    stats["added_summary"] += 1
                if not op.get("description") and description:
                    op["description"] = description

            if op.get("requestBody"):
                before = len(op["requestBody"].get("content") or {})
                op["requestBody"]["content"] = strip_unwanted_content_types(op["requestBody"].get("content", {}))
                stats["stripped_content_types"] += max(0, before - len(op["requestBody"]["content"]))
            for code, resp in (op.get("responses") or {}).items():
                if isinstance(resp, dict) and resp.get("content"):
                    before = len(resp["content"])
                    resp["content"] = strip_unwanted_content_types(resp["content"])
                    stats["stripped_content_types"] += max(0, before - len(resp["content"]))

            # Default error responses (4xx/5xx) — sadece eksik olanlari ekler
            op.setdefault("responses", {})
            has_body = op.get("requestBody") is not None
            for status, ref in default_error_responses(method, path, has_body).items():
                if status not in op["responses"]:
                    op["responses"][status] = ref
                    stats["added_default_responses"] += 1

            # x-codeSamples (top endpoint'ler icin)
            if "x-codeSamples" not in op:
                # Server URL'i specten cek
                server_url = ""
                if spec.get("servers"):
                    server_url = spec["servers"][0].get("url", "")
                samples = code_samples_for(path, method, server_url)
                if samples:
                    op["x-codeSamples"] = samples
                    stats["added_code_samples"] += 1

            keep_ops[method] = op

        if keep_ops:
            for k, v in ops.items():
                if k.lower() not in ("get","post","put","patch","delete","head","options") and k not in keep_ops:
                    keep_ops[k] = v
            new_paths[path] = keep_ops

    spec["paths"] = new_paths

    # Tag listesini yeniden ins a et — sadece referans alan, DROP_TAGS'ta olmayan
    referenced = set()
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if method.lower() in ("get","post","put","patch","delete"):
                for t in op.get("tags") or []:
                    referenced.add(t)

    existing_tags = spec.get("tags") or []
    seen_names = {t.get("name") for t in existing_tags}
    before_count = len(existing_tags)
    new_tags = []
    for t in existing_tags:
        name = t.get("name")
        if name in DROP_TAGS or name not in referenced:
            stats["stripped_empty_tags"] += 1
            continue
        if name in TAG_DISPLAY and not t.get("x-displayName"):
            t["x-displayName"] = TAG_DISPLAY[name]
            stats["tag_displays"] += 1
        new_tags.append(t)
    for name in referenced - seen_names:
        if name in DROP_TAGS:
            continue
        new_tags.append({
            "name": name,
            **({"x-displayName": TAG_DISPLAY[name]} if name in TAG_DISPLAY else {}),
        })
        stats["tag_displays"] += 1
    spec["tags"] = new_tags
    stats["stripped_tags"] = before_count - len(new_tags) + len(referenced - seen_names)

    return spec, stats


def main():
    print(f"Enriching {len(SPECS)} OpenAPI specs...\n")
    grand = {}
    for path in SPECS:
        if not path.exists():
            print(f"SKIP (missing): {path}")
            continue
        spec = json.loads(path.read_text())
        spec, stats = enrich_spec(spec)
        path.write_text(json.dumps(spec, indent=2, ensure_ascii=False))
        rel = path.relative_to(ROOT)
        print(f"== {rel} ==")
        for k, v in stats.items():
            grand[k] = grand.get(k, 0) + v
            print(f"  {k}: {v}")
        print()
    print("== TOTAL ==")
    for k, v in grand.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
