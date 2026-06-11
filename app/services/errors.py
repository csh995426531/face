from fastapi import HTTPException


def json_error(code: str, message: str, status_code=400):
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})
