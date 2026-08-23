import time

import httpx
import jwt
import pytest
import respx

from app.core.github_auth import create_app_jwt, get_installation_token

# Throwaway RSA key, generated once for tests only -- never a real App key.
TEST_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCZRumxi89MKza1
FXXIuz4w+TJVp8fFeiWp2CyxO7vxWGjo4f0ROUk4sHIeidqdx6k8wLtAYtsuxDPy
jXmwltrLaDGA8SyYy2+Y12IZlutO5u0ygKVbu2NlKT8rtqrSmti+ViJ/3dlbbSst
XTr9etSpiLVTBaafNGAuoajZnRQwU2IF5pUwROIL+kuTZK6ETF+ii8A9ThMX99ZA
z1kPdzlg3y3tjrVU6D7nbTeIOgY89EyMOd4WY5c4WzulUaezxUd5fXPdUhZBDd18
ZdrDoEEBwBU/p0RRVWrOTAOFPQS49KJ7iF8HT8idVoQZBftOBBpsdM6e6UYNK859
JPMVQfi9AgMBAAECggEABMMDN5TUV9Vv2ahVBGtsvzC+s5KGzkfBK8mfedIVQKYy
fCmpJwPUloJEyVYXCJfPVifWqWVo0ccepgZnJWlKWs9d2lejvwty6Bio34qkvMrH
y63bdUIZEGd7ouwF2o0c9qzOXZKS0hhOIxamYoGSYcHxgCbIymFiK5CyIjCTE/02
1uVHsLAdvwAEhKkTtTjibp89JJK6Jg9p6jOj036X+bYZIUx4Vm7EvOKKH/VDV/dQ
NCC/CofHYeAy7a8ZB6gA2VC4yEpge+1B++i/39GgOQvKb8AeYfs7VlcRZgraG9qf
+3SCxxY/2fKrP54RLK9/R/3lIa3aQlvbJNLytdeGgQKBgQDRImGWsusJ6M7ftZDj
jwGTi3Bw9DcNart2EmR4hY9XAXwTQiNRejqG/jAZ9M43huKJbKkFQFLZeJz3HDAB
MWhJnrI7aNW6/CidF0vKwVM4EP972THWGFlREDFIbQZXZKn2BjOdsJ5F0f6Ica42
3UkXPNT+k73/mPdKHI81xd5GKQKBgQC7oBwOViU7VDyVBdzMrk1a/T8Mas3ArIlU
aREY+kL7/Au8scGw8WxwiURIAyb91WvEs9DTZQz65oXWJ04SS+pBljIPlsq4Bk+i
02gL6fiI2x+4o//5xx2h1/SKK0tHZMvznYE8nHlQeYykWzuAswj5MPw2sscyTzlb
jZZNDbmodQKBgEM2wJSVhlLV/v8JNLreMEyCSS4UX0kxn3QwLxhJHKuC76Sk4gMC
vKK8OStucYSJFm/Ce4QTi00XpaMJ7SfFAFaA6ZmMdPy2pDrwzMwqXBut4t6kDI9Z
ngMeqCg12g7mbHWEwrwQkp2wAxVJLAu4DRCp3W7AfxURzZCFI0XOBUUZAoGAMJeF
zJy45cWqLvomtgfKVu9RfdjHUsgchPT1DZ/66yHatFLhE/9ikz6ppXDTj1fPolDj
m2wHUY+UR+NED+8DS1snuevWspRH2aagwr0kteTyMTKgH8NWxEyWs5YE2Aed3okD
KHxp2tKv/vz1yx4TC96I422nszrbYv+nVmtgkuUCgYEAktSzdGnLeShVWYxN+aQ1
XcO51tRKilQey+FSzEYtbxjdC8DEN00FHq+rRvbs5xfbZCUo0IL2ZCEgWyr4/phy
/fSOT6PDJkNar0EagZQCPXesvsO/9j/9keqx8f8LARBC5mgu+LKZ/+0dx7oVAcye
bEmZ9+RJR7uDhyQ3Indvnvg=
-----END PRIVATE KEY-----"""


def test_create_app_jwt_has_expected_claims():
    token = create_app_jwt("12345", TEST_PRIVATE_KEY)
    decoded = jwt.decode(token, options={"verify_signature": False})
    assert decoded["iss"] == "12345"
    now = int(time.time())
    assert decoded["iat"] <= now
    assert decoded["exp"] > now


@respx.mock
async def test_get_installation_token_returns_the_token_from_the_response():
    route = respx.post(
        "https://api.github.com/app/installations/999/access_tokens"
    ).mock(return_value=httpx.Response(201, json={"token": "ghs_faketoken"}))

    token = await get_installation_token("fake-app-jwt", 999)

    assert token == "ghs_faketoken"
    assert route.called
    sent_headers = route.calls[0].request.headers
    assert sent_headers["authorization"] == "Bearer fake-app-jwt"
    assert sent_headers["x-github-api-version"] == "2022-11-28"


@respx.mock
async def test_get_installation_token_raises_on_error_response():
    respx.post("https://api.github.com/app/installations/999/access_tokens").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await get_installation_token("fake-app-jwt", 999)
