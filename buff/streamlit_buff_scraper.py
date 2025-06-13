import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title="BUFF 饰品数据展示", layout="wide")

st.title("🎯 BUFF CSGO 饰品数据浏览器")

DATA_PATH = "buff_csgo_data.csv"

if not os.path.exists(DATA_PATH):
    st.warning("⚠️ 尚未发现数据文件，请先运行 buff_scraper.py 抓取数据。")
else:
    df = pd.read_csv(DATA_PATH)

    st.success(f"✅ 成功加载数据，共 {len(df)} 个饰品。")

    keyword = st.text_input("🔍 输入关键词搜索饰品名")
    if keyword:
        df = df[df["名称"].str.contains(keyword, case=False, na=False)]

    st.dataframe(df)

    with st.expander("📊 数据概览图"):
        st.bar_chart(df.sort_values("最低价格", ascending=False).head(20).set_index("名称")["最低价格"])

    st.download_button("📥 下载为 CSV", df.to_csv(index=False).encode("utf-8-sig"), file_name="buff_items.csv")
