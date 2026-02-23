"""
BRIM CS 返答自動生成システム v4 (Supabase対応)
- PostgreSQL (Supabase) データベース
- 環境変数対応
- クラウドデプロイ対応
"""

import streamlit as st
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List
import anthropic
import os
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import func

# ページ設定
st.set_page_config(
    page_title="BRIM CS 返答生成システム",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# カテゴリと問い合わせ経路の定義
CATEGORIES = [
    "製品仕様・スペック", "UV・紫外線", "使用方法", "電気代・ランニングコスト",
    "タイマー機能", "設置・取り付け", "植物適合性", "故障・不具合",
    "購入前相談", "製品比較", "配送・在庫", "返品・交換",
    "保証・アフターサービス", "その他"
]

INQUIRY_CHANNELS = ["エルメ", "MD_Amazon", "MD_楽天", "MD_公式", "その他"]

# =============================================================================
# データベース設定
# =============================================================================

# 環境変数から接続情報を取得
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    st.error("❌ DATABASE_URL環境変数が設定されていません")
    st.stop()

# SQLAlchemy設定
Base = declarative_base()

class Inquiry(Base):
    __tablename__ = 'inquiries'
    
    id = Column(Integer, primary_key=True)
    inquiry_text = Column(Text, nullable=False)
    category = Column(String(100))
    inquiry_channel = Column(String(50))
    created_at = Column(DateTime, default=func.now())
    created_by = Column(String(100))
    
    ai_responses = relationship("AIResponse", back_populates="inquiry")

class AIResponse(Base):
    __tablename__ = 'ai_responses'
    
    id = Column(Integer, primary_key=True)
    inquiry_id = Column(Integer, ForeignKey('inquiries.id'))
    generated_response = Column(Text, nullable=False)
    prompt_version = Column(String(20), default='v4')
    created_at = Column(DateTime, default=func.now())
    
    inquiry = relationship("Inquiry", back_populates="ai_responses")
    corrections = relationship("HumanCorrection", back_populates="ai_response")
    feedbacks = relationship("Feedback", back_populates="ai_response")

class HumanCorrection(Base):
    __tablename__ = 'human_corrections'
    
    id = Column(Integer, primary_key=True)
    ai_response_id = Column(Integer, ForeignKey('ai_responses.id'))
    corrected_response = Column(Text, nullable=False)
    correction_notes = Column(Text)
    corrected_by = Column(String(100))
    created_at = Column(DateTime, default=func.now())
    
    ai_response = relationship("AIResponse", back_populates="corrections")

class Feedback(Base):
    __tablename__ = 'feedbacks'
    
    id = Column(Integer, primary_key=True)
    ai_response_id = Column(Integer, ForeignKey('ai_responses.id'))
    rating = Column(String(10))
    feedback_text = Column(Text)
    created_at = Column(DateTime, default=func.now())
    
    ai_response = relationship("AIResponse", back_populates="feedbacks")

# データベース接続
@st.cache_resource
def get_engine():
    return create_engine(DATABASE_URL)

@st.cache_resource
def init_database():
    engine = get_engine()
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)

Session = init_database()

# =============================================================================
# BRIMデータベースクラス
# =============================================================================

class BRIMProductDatabase:
    def __init__(self, db_path: str = 'brim_product_database.json'):
        try:
            with open(db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.products = data['products']
        except FileNotFoundError:
            st.error(f"❌ {db_path} が見つかりません")
            self.products = {}
    
    def search_products(self, query: str) -> List[Dict]:
        results = []
        query_lower = query.lower()
        for sku, product in self.products.items():
            if query_lower in product.get('product_name', '').lower():
                results.append({**product, 'sku': sku})
        return results

# =============================================================================
# Claude API返答生成
# =============================================================================

def generate_response_with_claude(inquiry_text: str, api_key: str, product_db: BRIMProductDatabase) -> str:
    """Claude APIで返答を生成"""
    
    # 製品情報を取得
    product_context = ""
    for keyword in ['COSMO', 'SOL', 'LUNA', 'FLORA', 'PANEL']:
        if keyword in inquiry_text:
            products = product_db.search_products(keyword)
            if products:
                product_context += f"\n【{keyword}の製品情報】\n"
                for p in products[:3]:
                    specs = p.get('specifications', {})
                    product_context += f"- {p['product_name']}\n"
                    product_context += f"  消費電力: {specs.get('power_consumption', '不明')}\n"
                    product_context += f"  PPFD: {specs.get('ppfd', '不明')}\n"
    
    system_prompt = """あなたはBRIM（植物育成ライト専門メーカー）のカスタマーサポート担当者です。

【重要な対応方針】
1. 丁寧で親切な対応を心がける
2. 製品情報データベースの情報を活用する
3. 専門用語は適切に説明する
4. 購入検討中の方には不安を解消する情報を提供
5. 既存顧客には製品の最大活用法を提案

【返答のトーン】
- プロフェッショナルだが親しみやすい
- 技術的に正確
- 簡潔で分かりやすい

【返答の構成】
1. 挨拶とお礼
2. 質問への回答（箇条書きや見出しを活用）
3. 追加情報や提案
4. 締めの言葉"""

    user_prompt = f"""以下の問い合わせに対して、適切な返答を生成してください。

【問い合わせ内容】
{inquiry_text}

【製品情報データベース】
{product_context if product_context else "（該当する製品情報なし）"}

上記の情報を参考に、カスタマーサポートとして適切な返答を作成してください。"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        return message.content[0].text
    except Exception as e:
        return f"❌ エラーが発生しました: {str(e)}"

# =============================================================================
# データベース操作
# =============================================================================

def save_inquiry(session, inquiry_text: str, category: str, channel: str, created_by: str):
    inquiry = Inquiry(
        inquiry_text=inquiry_text,
        category=category,
        inquiry_channel=channel,
        created_by=created_by
    )
    session.add(inquiry)
    session.commit()
    return inquiry.id

def save_ai_response(session, inquiry_id: int, response_text: str):
    response = AIResponse(
        inquiry_id=inquiry_id,
        generated_response=response_text
    )
    session.add(response)
    session.commit()
    return response.id

def save_correction(session, ai_response_id: int, corrected_text: str, notes: str, corrected_by: str):
    correction = HumanCorrection(
        ai_response_id=ai_response_id,
        corrected_response=corrected_text,
        correction_notes=notes,
        corrected_by=corrected_by
    )
    session.add(correction)
    session.commit()

def save_feedback(session, ai_response_id: int, rating: str):
    feedback = Feedback(
        ai_response_id=ai_response_id,
        rating=rating
    )
    session.add(feedback)
    session.commit()

def get_stats(session, start_date=None, end_date=None):
    """統計情報を取得"""
    query = session.query(Inquiry)
    
    if start_date and end_date:
        query = query.filter(Inquiry.created_at.between(start_date, end_date))
    
    total = query.count()
    
    # GOOD/BAD評価
    good = session.query(Feedback).join(AIResponse).join(Inquiry).filter(
        Feedback.rating == 'good'
    )
    bad = session.query(Feedback).join(AIResponse).join(Inquiry).filter(
        Feedback.rating == 'bad'
    )
    
    if start_date and end_date:
        good = good.filter(Inquiry.created_at.between(start_date, end_date))
        bad = bad.filter(Inquiry.created_at.between(start_date, end_date))
    
    good_count = good.count()
    bad_count = bad.count()
    
    # 修正回数
    corrections = session.query(HumanCorrection).join(AIResponse).join(Inquiry)
    if start_date and end_date:
        corrections = corrections.filter(Inquiry.created_at.between(start_date, end_date))
    
    corrections_count = corrections.count()
    
    # カテゴリ別
    category_query = query.with_entities(
        Inquiry.category, 
        func.count(Inquiry.id)
    ).group_by(Inquiry.category).all()
    
    by_category = {cat: count for cat, count in category_query if cat}
    
    # 経路別
    channel_query = query.with_entities(
        Inquiry.inquiry_channel,
        func.count(Inquiry.id)
    ).group_by(Inquiry.inquiry_channel).all()
    
    by_channel = {ch: count for ch, count in channel_query if ch}
    
    return {
        'total': total,
        'good': good_count,
        'bad': bad_count,
        'corrections': corrections_count,
        'by_category': by_category,
        'by_channel': by_channel
    }

def get_correction_history(session, limit=20):
    """修正履歴を取得"""
    corrections = session.query(HumanCorrection).join(AIResponse).join(Inquiry).order_by(
        HumanCorrection.created_at.desc()
    ).limit(limit).all()
    
    return [
        (
            c.id,
            c.ai_response.inquiry.inquiry_text,
            c.ai_response.generated_response,
            c.corrected_response,
            c.correction_notes,
            c.corrected_by,
            c.created_at
        )
        for c in corrections
    ]

# =============================================================================
# メインアプリ
# =============================================================================

def main():
    product_db = BRIMProductDatabase()
    session = Session()
    
    # サイドバー
    with st.sidebar:
        st.title("🎯 BRIM CS システム")
        st.markdown("---")
        
        # APIキー設定
        st.subheader("🔑 API設定")
        api_key = st.text_input("Claude API Key", type="password", value=os.getenv("CLAUDE_API_KEY", ""))
        
        if api_key:
            st.success("✅ APIキー設定済み")
        else:
            st.warning("⚠️ APIキーを入力")
        
        st.markdown("---")
        
        page = st.radio(
            "📍 メニュー",
            ["💬 問い合わせ処理", "📊 ダッシュボード", "🎓 学習履歴"],
            label_visibility="collapsed"
        )
    
    # ページ1: 問い合わせ処理
    if page == "💬 問い合わせ処理":
        st.title("💬 問い合わせ返答生成")
        
        if not api_key:
            st.error("🔑 左サイドバーでClaude APIキーを入力してください")
            st.stop()
        
        col1, col2, col3 = st.columns([2, 2, 2])
        
        with col1:
            user_name = st.text_input("👤 担当者名", value="担当者")
        
        with col2:
            category = st.selectbox("📁 カテゴリ", CATEGORIES)
        
        with col3:
            channel = st.selectbox("📮 問い合わせ経路", INQUIRY_CHANNELS)
        
        st.markdown("---")
        
        st.subheader("📝 問い合わせ内容")
        inquiry = st.text_area(
            "問い合わせ文を入力してください",
            height=200,
            placeholder="問い合わせ内容を貼り付けてください..."
        )
        
        if st.button("🤖 AI返答を生成", type="primary", use_container_width=True):
            if inquiry:
                with st.spinner("🔄 Claude APIで返答を生成中..."):
                    inquiry_id = save_inquiry(session, inquiry, category, channel, user_name)
                    response = generate_response_with_claude(inquiry, api_key, product_db)
                    response_id = save_ai_response(session, inquiry_id, response)
                    
                    st.session_state.current_inquiry_id = inquiry_id
                    st.session_state.current_response_id = response_id
                    st.session_state.current_response = response
        
        # 生成された返答
        if 'current_response' in st.session_state:
            st.markdown("---")
            st.subheader("✅ 生成された返答")
            
            edited_response = st.text_area(
                "返答を確認・修正してください",
                value=st.session_state.current_response,
                height=400,
                key="response_editor"
            )
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if st.button("✅ GOOD", use_container_width=True):
                    save_feedback(session, st.session_state.current_response_id, 'good')
                    st.success("✅ GOOD評価を保存")
            
            with col2:
                if st.button("❌ BAD", use_container_width=True):
                    save_feedback(session, st.session_state.current_response_id, 'bad')
                    st.warning("❌ BAD評価を保存")
            
            with col3:
                if st.button("💾 修正を保存して学習", use_container_width=True):
                    if edited_response != st.session_state.current_response:
                        save_correction(
                            session,
                            st.session_state.current_response_id,
                            edited_response,
                            "手動修正",
                            user_name
                        )
                        st.success("💾 修正内容を学習データとして保存しました！")
    
    # ページ2: ダッシュボード
    elif page == "📊 ダッシュボード":
        st.title("📊 学習状況ダッシュボード")
        
        # 期間選択
        col1, col2, col3 = st.columns([2, 2, 2])
        
        with col1:
            period = st.selectbox("📅 期間", ["全期間", "当月", "先月", "直近7日", "直近30日"])
        
        start_date, end_date = None, None
        
        if period == "当月":
            start_date = datetime.now().replace(day=1)
            end_date = datetime.now()
        elif period == "先月":
            last_month = datetime.now().replace(day=1) - timedelta(days=1)
            start_date = last_month.replace(day=1)
            end_date = last_month
        elif period == "直近7日":
            start_date = datetime.now() - timedelta(days=7)
            end_date = datetime.now()
        elif period == "直近30日":
            start_date = datetime.now() - timedelta(days=30)
            end_date = datetime.now()
        
        stats = get_stats(session, start_date, end_date)
        
        # KPI表示
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("📊 総問い合わせ数", f"{stats['total']}件")
        
        with col2:
            good_rate = (stats['good'] / max(stats['total'], 1)) * 100
            st.metric("✅ GOOD評価", f"{stats['good']}件", f"{good_rate:.1f}%")
        
        with col3:
            bad_rate = (stats['bad'] / max(stats['total'], 1)) * 100
            st.metric("❌ BAD評価", f"{stats['bad']}件", f"{bad_rate:.1f}%")
        
        with col4:
            st.metric("💾 修正回数", f"{stats['corrections']}件")
        
        st.markdown("---")
        
        # グラフ
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📁 カテゴリ別")
            if stats['by_category']:
                st.bar_chart(stats['by_category'])
            else:
                st.info("データがありません")
        
        with col2:
            st.subheader("📮 問い合わせ経路別")
            if stats['by_channel']:
                st.bar_chart(stats['by_channel'])
            else:
                st.info("データがありません")
    
    # ページ3: 学習履歴
    elif page == "🎓 学習履歴":
        st.title("🎓 修正・学習履歴")
        
        corrections = get_correction_history(session, 50)
        
        if not corrections:
            st.info("まだ学習データがありません")
        else:
            for item in corrections:
                corr_id, inquiry, ai_resp, corrected, notes, by, created_at = item
                
                with st.expander(f"🔄 #{corr_id} - {created_at} (修正者: {by})"):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**AI生成（修正前）**")
                        st.text_area("", value=ai_resp, height=200, key=f"ai_{corr_id}", disabled=True)
                    
                    with col2:
                        st.markdown("**人間による修正**")
                        st.text_area("", value=corrected, height=200, key=f"corr_{corr_id}", disabled=True)
                    
                    if notes:
                        st.info(f"📝 修正理由: {notes}")
    
    session.close()

if __name__ == "__main__":
    main()
