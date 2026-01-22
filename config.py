from pydantic import BaseModel, Field


class Config(BaseModel):
    # --- API ---
    vr_gift_api_base: str = Field(
        default="https://vr.qianqiuzy.cn/gift",
        description="VR礼物统计 API 基址（不含 /by_month）",
    )
    psp_gift_api_base: str = Field(
        default="https://psp.qianqiuzy.cn/gift",
        description="PSP礼物统计 API 基址（不含 /by_month）",
    )

    # --- Titles ---
    vr_douchong_title: str = Field(default="VR斗虫", description="VR斗虫图片标题")
    psp_douchong_title: str = Field(default="PSP斗虫", description="PSP斗虫图片标题")
    vr_live_title: str = Field(default="VR开播", description="VR开播图片标题")
    psp_live_title: str = Field(default="PSP开播", description="PSP开播图片标题")

    # --- HTTP ---
    vr_http_timeout: float = Field(default=5.0, description="HTTP 请求超时（秒）")
