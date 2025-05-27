from dataclasses import dataclass


@dataclass
class Config:
    COGNITO_URL: str = "https://qgishubv3.auth.ap-northeast-1.amazoncognito.com"
    COGNITO_CLIENT_ID: str = "49fnn61i1bh3jongq62i290461"
    API_URL: str = "https://d3eqzgssnrhp33.cloudfront.net/api"


config = Config(
    COGNITO_URL="https://qgishubv3.auth.ap-northeast-1.amazoncognito.com",
    COGNITO_CLIENT_ID="49fnn61i1bh3jongq62i290461",
    API_URL="http://localhost:3000/api",
)
