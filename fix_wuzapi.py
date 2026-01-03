import requests
from temba.channels.models import Channel

print("Starting Wuzapi Webhook Repair...")
channels = Channel.objects.filter(channel_type='WZ', is_active=True)
print(f"Found {channels.count()} active Wuzapi channels.")

for c in channels:
    print(f"Processing Channel {c.uuid}...")
    w_url = c.config.get('wuzapi_url')
    w_token = c.config.get('wuzapi_token')
    
    if not w_url or not w_token:
        print("  - Missing URL or Token in config. Skipping.")
        continue

    # FORCE HTTP and LOCALHOST
    # This is the "Professional" Fix for native setup
    target_url = f"http://127.0.0.1:8080/c/wz/{c.uuid}/receive"
    
    payload = {
        "webhookurl": target_url,
        "events": ["Message", "ReadReceipt"]
    }
    
    print(f"  - Setting Webhook to: {target_url}")
    
    try:
        # 1. Update Webhook
        res = requests.post(
            f"{w_url}/webhook",
            json=payload,
            headers={"Authorization": w_token, "Content-Type": "application/json"},
            timeout=5
        )
        print(f"  - Wuzapi Response: {res.status_code} {res.text}")
        
        # 2. Ensure HMAC is pushed too if present
        hmac_key = c.config.get('hmac_key')
        if hmac_key:
             res2 = requests.post(
                 f"{w_url}/session/hmac/config",
                 json={"hmac_key": hmac_key},
                 headers={"Authorization": w_token, "Content-Type": "application/json"},
                 timeout=5
             )
             print(f"  - HMAC Push Response: {res2.status_code}")
             
    except Exception as e:
        print(f"  - ERROR: {e}")

print("Repair Complete.")
