import random
import string
import hashlib
import streamlit as st
import hashlib
import hmac
import streamlit as st

def GenerateKey():
    # 1. Generate 8 random characters (capital letters and numbers) [1]
    charset = string.ascii_uppercase + string.digits
    random_chars = ''.join(random.choices(charset, k=8))
    
    # 2. Retrieve the secret key under [KeyTester] secret_key [1]
    secret_key = st.secrets["KeyTester"]["secret_key"]
    
    # 3. Encode the 8 characters with the secret key into capital letters/numbers [1]
    hash_input = (random_chars + secret_key).encode('utf-8')
    digest = hashlib.sha256(hash_input).hexdigest().upper()
    encoded_chars = digest[:8]  # Extract 8 encoded characters
    
    # 4. Interlace the random and encoded characters [1]
    interlaced_key = ''.join(r + e for r, e in zip(random_chars, encoded_chars))
    
    return interlaced_key

def ValidKey(key: str) -> bool:
    """
    Validates a boat key according to the project specifications.
    Returns True if the key is valid, False otherwise.
    """
    # 1. Sanitize input and verify basic formatting (16 uppercase alphanumeric characters)
    if not isinstance(key, str):
        return False
    
    key = key.strip().upper()
    if len(key) != 16 or not key.isalnum():
        return False

    # 2. De-interlace the key into random characters (even indices) and encoded characters (odd indices)
    random_chars = "".join(key[i] for i in range(0, 16, 2))
    provided_encoded = "".join(key[i] for i in range(1, 16, 2))

    try:
        # 3. Retrieve the secret key from Streamlit secrets [KeyTester]
        secret_key = st.secrets["KeyTester"]["secret_key"]
    except Exception:
        return False

    # 4. Re-calculate the expected 8 encoded characters
    hash_input = (random_chars + secret_key).encode('utf-8')
    expected_encoded = hashlib.sha256(hash_input).hexdigest().upper()[:8]

    # 5. Constant-time comparison to verify validity
    return hmac.compare_digest(provided_encoded, expected_encoded)

