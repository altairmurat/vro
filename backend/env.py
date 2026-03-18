from dotenv import load_dotenv
import os

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")

DATABASE_URL = os.getenv("DATABASE_URL")

API_FRONT = os.getenv("API_FRONT")