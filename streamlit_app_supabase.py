"""
BRIM CS 返答自動生成システム v5 (RAG対応)
- Supabase pgvector によるベクトル類似検索
- 既存5,000件Q&A + 商品情報を活用
- 修正データをベクトル化して学習（brim_qaに追加）
- 使えば使うほど精度が上がるシステム
"""

import streamlit as st
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, List
import anthropic
import os
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
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

DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not DATABASE_URL:
    st.error("❌ DATABASE_URL環境変数が設定されていません")
    st.stop()

if not OPENAI_API_KEY:
    st.error("❌ OPENAI_API_KEY環境変数が設定されていません")
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
    prompt_version = Column(String(20), default='v5_rag')
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
    return create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)

@st.cache_resource
def init_database():
    engine = get_engine()
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)

Session = init_database()

# =============================================================================
# OpenAI Embedding
# =============================================================================

def get_embedding(text_input: str) -> List[float]:
    """OpenAI APIでテキストをベクトル化"""
    try:
        response = requests.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "text-embedding-3-small",
                "input": text_input
            },
            timeout=30
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]
    except Exception as e:
        st.error(f"❌ Embedding生成エラー: {str(e)}")
        return None

# =============================================================================
# RAG検索: brim_qaからベクトル類似検索
# =============================================================================

def search_similar_qa(session, query_text: str, top_k: int = 5) -> List[Dict]:
    """問い合わせ内容に類似するQ&Aをベクトル検索で取得"""
    embedding = get_embedding(query_text)
    if embedding is None:
        return []
    
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    
    try:
        sql = text("""
            SELECT id, question, answer, category, platform,
                   1 - (embedding <=> cast(:emb AS vector)) AS similarity
            FROM brim_qa
            ORDER BY embedding <=> cast(:emb AS vector)
            LIMIT :top_k
        """)
        
        result = session.execute(sql, {"emb": embedding_str, "top_k": top_k})
        rows = result.fetchall()
        
        return [
            {
                "id": row[0],
                "question": row[1],
                "answer": row[2],
                "category": row[3],
                "platform": row[4],
                "similarity": round(float(row[5]), 4)
            }
            for row in rows
        ]
    except Exception as e:
        st.error(f"❌ 類似検索エラー: {str(e)}")
        return []

# =============================================================================
# 修正データをbrim_qaに追加（学習）
# =============================================================================

def add_correction_to_qa(session, question: str, corrected_answer: str, category: str, platform: str = "修正データ"):
    """修正された回答をベクトル化してbrim_qaテーブルに追加"""
    # 質問文をベクトル化
    embedding = get_embedding(question)
    if embedding is None:
        return False
    
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
    
    try:
        sql = text("""
            INSERT INTO brim_qa (question, answer, platform, category, embedding, created_at)
            VALUES (:question, :answer, :platform, :category, cast(:emb AS vector), NOW())
        """)
        
        session.execute(sql, {
            "question": question,
            "answer": corrected_answer,
            "platform": platform,
            "category": category,
            "emb": embedding_str
        })
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        st.error(f"❌ 学習データ追加エラー: {str(e)}")
        return False

# =============================================================================
# 商品情報データベース
# =============================================================================

class BRIMProductDatabase:
    def __init__(self, db_path: str = 'brim_product_database.json'):
        try:
            with open(db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.products = data.get('products', {})
        except FileNotFoundError:
            self.products = {}
    
    def search_products(self, query: str) -> List[Dict]:
        results = []
        query_lower = query.lower()
        for sku, product in self.products.items():
            name = product.get('product_name', '').lower()
            category = product.get('category', '').lower()
            if query_lower in name or query_lower in category:
                results.append({**product, 'sku': sku})
        return results
    
    def get_all_product_summary(self) -> str:
        """全商品の概要テキストを生成"""
        summary = []
        for sku, p in self.products.items():
            name = p.get('product_name', '')
            specs = p.get('specifications', {})
            power = specs.get('power_consumption', '')
            ppfd = specs.get('ppfd', '')
            line = f"- {name} (SKU:{sku})"
            if power:
                line += f" 消費電力:{power}"
            if ppfd:
                line += f" PPFD:{ppfd}"
            summary.append(line)
        return "\n".join(summary[:30])  # 上位30件

    def search_relevant_products(self, query: str) -> str:
        """問い合わせに関連する商品情報を詳細に返す"""
        keywords = ['COSMO', 'SOL', 'LUNA', 'FLORA', 'PANEL', 'パネル', 'クリップ',
                     'ヒートマット', 'HMT', 'シェード', 'ソケット', 'タイマー',
                     'cosmo', 'sol', 'luna', 'flora', 'panel']
        
        found_products = []
        query_upper = query.upper()
        
        for keyword in keywords:
            if keyword.upper() in query_upper:
                products = self.search_products(keyword)
                found_products.extend(products)
        
        if not found_products:
            # キーワードが見つからない場合、全商品から部分一致
            for sku, product in self.products.items():
                name = product.get('product_name', '').lower()
                for word in query.lower().split():
                    if len(word) >= 2 and word in name:
                        found_products.append({**product, 'sku': sku})
                        break
        
        if not found_products:
            return ""
        
        # 重複除去
        seen = set()
        unique = []
        for p in found_products:
            sku = p.get('sku', '')
            if sku not in seen:
                seen.add(sku)
                unique.append(p)
        
        context = ""
        for p in unique[:5]:  # 最大5件
            context += f"\n【{p.get('product_name', '')}】(SKU: {p.get('sku', '')})\n"
            specs = p.get('specifications', {})
            if specs:
                for k, v in specs.items():
                    context += f"  {k}: {v}\n"
            usage = p.get('usage', {})
            if usage:
                for k, v in usage.items():
                    if isinstance(v, list):
                        context += f"  {k}: {', '.join(v)}\n"
                    else:
                        context += f"  {k}: {v}\n"
            features = p.get('features', {})
            if features:
                kp = features.get('key_points', [])
                if kp:
                    context += f"  特徴: {', '.join(kp)}\n"
            faq = p.get('faq', [])
            if faq:
                context += "  よくある質問:\n"
                for qa in faq:
                    context += f"    Q: {qa['question']}\n    A: {qa['answer']}\n"
        
        return context

# =============================================================================
# Claude API返答生成（RAG対応）
# =============================================================================

def generate_response_with_claude(inquiry_text: str, api_key: str, 
                                   similar_qa: List[Dict], product_context: str) -> str:
    """類似Q&A + 商品情報を使ってClaude APIで返答を生成"""
    
    # 類似Q&Aをコンテキストとして構築
    qa_context = ""
    if similar_qa:
        qa_context = "【過去の類似問い合わせと回答】\n"
        for i, qa in enumerate(similar_qa, 1):
            qa_context += f"\n--- 類似事例 {i} (類似度: {qa['similarity']}) ---\n"
            qa_context += f"問い合わせ: {qa['question'][:300]}\n"
            qa_context += f"回答: {qa['answer'][:500]}\n"
    
    system_prompt = """あなたはBRIM（植物育成ライト専門メーカー）のカスタマーサポート担当者です。

【重要な対応方針】
1. 過去の類似問い合わせの回答を最も重要な参考にしてください
2. 商品情報データベースの情報で技術的に正確な回答をしてください
3. 丁寧で親切な対応を心がけてください
4. 専門用語は適切に説明してください
5. 過去の回答のトーンや言い回しをなるべく踏襲してください

【代替商品の提案】
お客様が求める機能が当該製品にない場合（例：調光機能、防水、特定のサイズなど）は、
その機能を備えたBRIMの別製品を積極的に提案してください。
例：「調光機能をご希望でしたら、PANEL YやPANEL Xもご検討いただけます」
提案する際は、なぜその製品が適しているか理由も簡潔に添えてください。

【返答のトーン】
- プロフェッショナルだが親しみやすい
- 技術的に正確
- 簡潔で分かりやすい
- BRIMの既存の対応スタイルに合わせる

【注意事項】
- 署名は不要です（「BRIMカスタマーサポート」などの署名は付けないでください）
- 確実でない情報は「確認いたします」と伝えてください
- 過去の回答例がある場合は、その回答スタイルを参考にしてください"""

    user_prompt = f"""以下の問い合わせに対して、適切な返答を生成してください。

【問い合わせ内容】
{inquiry_text}

{qa_context}

{f"【関連商品情報】{product_context}" if product_context else ""}

上記の過去の類似事例と商品情報を参考に、カスタマーサポートとして適切な返答を作成してください。
過去の回答のトーンや対応方針をできるだけ踏襲してください。"""

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
        inquiry_text=inquiry_text, category=category,
        inquiry_channel=channel, created_by=created_by
    )
    session.add(inquiry)
    session.commit()
    return inquiry.id

def save_ai_response(session, inquiry_id: int, response_text: str):
    response = AIResponse(inquiry_id=inquiry_id, generated_response=response_text)
    session.add(response)
    session.commit()
    return response.id

def save_correction(session, ai_response_id: int, corrected_text: str, notes: str, corrected_by: str):
    correction = HumanCorrection(
        ai_response_id=ai_response_id, corrected_response=corrected_text,
        correction_notes=notes, corrected_by=corrected_by
    )
    session.add(correction)
    session.commit()

def save_feedback(session, ai_response_id: int, rating: str):
    feedback = Feedback(ai_response_id=ai_response_id, rating=rating)
    session.add(feedback)
    session.commit()

def get_stats(session, start_date=None, end_date=None):
    query = session.query(Inquiry)
    if start_date and end_date:
        query = query.filter(Inquiry.created_at.between(start_date, end_date))
    total = query.count()
    
    good = session.query(Feedback).join(AIResponse).join(Inquiry).filter(Feedback.rating == 'good')
    bad = session.query(Feedback).join(AIResponse).join(Inquiry).filter(Feedback.rating == 'bad')
    if start_date and end_date:
        good = good.filter(Inquiry.created_at.between(start_date, end_date))
        bad = bad.filter(Inquiry.created_at.between(start_date, end_date))
    good_count = good.count()
    bad_count = bad.count()
    
    corrections = session.query(HumanCorrection).join(AIResponse).join(Inquiry)
    if start_date and end_date:
        corrections = corrections.filter(Inquiry.created_at.between(start_date, end_date))
    corrections_count = corrections.count()
    
    category_query = query.with_entities(
        Inquiry.category, func.count(Inquiry.id)
    ).group_by(Inquiry.category).all()
    by_category = {cat: count for cat, count in category_query if cat}
    
    channel_query = query.with_entities(
        Inquiry.inquiry_channel, func.count(Inquiry.id)
    ).group_by(Inquiry.inquiry_channel).all()
    by_channel = {ch: count for ch, count in channel_query if ch}
    
    # brim_qaの総数を取得
    try:
        qa_total = session.execute(text("SELECT COUNT(*) FROM brim_qa")).scalar()
        learned = session.execute(
            text("SELECT COUNT(*) FROM brim_qa WHERE platform = '修正データ'")
        ).scalar()
    except:
        qa_total = 0
        learned = 0
    
    return {
        'total': total, 'good': good_count, 'bad': bad_count,
        'corrections': corrections_count, 'by_category': by_category,
        'by_channel': by_channel, 'qa_total': qa_total, 'learned': learned
    }

def get_correction_history(session, limit=20):
    corrections = session.query(HumanCorrection).join(AIResponse).join(Inquiry).order_by(
        HumanCorrection.created_at.desc()
    ).limit(limit).all()
    return [
        (c.id, c.ai_response.inquiry.inquiry_text, c.ai_response.generated_response,
         c.corrected_response, c.correction_notes, c.corrected_by, c.created_at)
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
        st.caption("v5 - RAG対応版")
        st.markdown("---")
        
        # APIキー設定
        st.subheader("🔑 API設定")
        api_key = st.text_input("Claude API Key", type="password", 
                                value=os.getenv("CLAUDE_API_KEY", ""))
        
        if api_key:
            st.success("✅ APIキー設定済み")
        else:
            st.warning("⚠️ APIキーを入力")
        
        st.markdown("---")
        
        # RAGステータス表示
        try:
            qa_count = session.execute(text("SELECT COUNT(*) FROM brim_qa")).scalar()
            learned_count = session.execute(
                text("SELECT COUNT(*) FROM brim_qa WHERE platform = '修正データ'")
            ).scalar()
            st.metric("📚 知識ベース", f"{qa_count}件")
            st.metric("🎓 学習済み修正", f"{learned_count}件")
        except:
            st.info("📚 知識ベース: 確認中...")
        
        st.markdown("---")
        
        page = st.radio(
            "📍 メニュー",
            ["💬 問い合わせ処理", "📊 ダッシュボード", "🎓 学習履歴"],
            label_visibility="collapsed"
        )
    
    # =========================================================================
    # ページ1: 問い合わせ処理
    # =========================================================================
    if page == "💬 問い合わせ処理":
        st.title("💬 問い合わせ返答生成")
        st.caption("RAGシステム: 過去のQ&A + 商品情報 + 学習データを活用して回答を生成します")
        
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
                with st.spinner("🔍 類似Q&Aを検索中..."):
                    similar_qa = search_similar_qa(session, inquiry, top_k=5)
                
                with st.spinner("📦 関連商品情報を取得中..."):
                    product_context = product_db.search_relevant_products(inquiry)
                
                with st.spinner("🤖 Claude APIで返答を生成中..."):
                    inquiry_id = save_inquiry(session, inquiry, category, channel, user_name)
                    response = generate_response_with_claude(
                        inquiry, api_key, similar_qa, product_context
                    )
                    response_id = save_ai_response(session, inquiry_id, response)
                    
                    st.session_state.current_inquiry_id = inquiry_id
                    st.session_state.current_response_id = response_id
                    st.session_state.current_response = response
                    st.session_state.current_inquiry_text = inquiry
                    st.session_state.current_category = category
                    st.session_state.similar_qa = similar_qa
        
        # 生成された返答
        if 'current_response' in st.session_state:
            st.markdown("---")
            
            # 類似Q&A参照情報を表示
            if 'similar_qa' in st.session_state and st.session_state.similar_qa:
                with st.expander(f"🔍 参照した類似Q&A ({len(st.session_state.similar_qa)}件)", expanded=False):
                    for i, qa in enumerate(st.session_state.similar_qa, 1):
                        similarity_pct = qa['similarity'] * 100
                        st.markdown(f"**類似事例 {i}** (類似度: {similarity_pct:.1f}%)")
                        st.markdown(f"📩 問い合わせ: {qa['question'][:200]}...")
                        st.markdown(f"📤 回答: {qa['answer'][:200]}...")
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
                    st.success("✅ GOOD評価を保存しました")
            
            with col2:
                if st.button("❌ BAD", use_container_width=True):
                    save_feedback(session, st.session_state.current_response_id, 'bad')
                    st.warning("❌ BAD評価を保存しました")
            
            with col3:
                if st.button("💾 修正を保存して学習", use_container_width=True):
                    if edited_response != st.session_state.current_response:
                        # 1. human_correctionsテーブルに保存
                        save_correction(
                            session, st.session_state.current_response_id,
                            edited_response, "手動修正", user_name
                        )
                        
                        # 2. brim_qaテーブルに追加（ベクトル化して学習）
                        success = add_correction_to_qa(
                            session,
                            st.session_state.current_inquiry_text,
                            edited_response,
                            st.session_state.current_category
                        )
                        
                        if success:
                            st.success("🎓 修正内容を学習しました！次回から同様の問い合わせに反映されます。")
                        else:
                            st.warning("💾 修正は保存されましたが、学習データへの追加に失敗しました。")
                    else:
                        st.info("💡 返答が変更されていません。テキストを修正してから保存してください。")
    
    # =========================================================================
    # ページ2: ダッシュボード
    # =========================================================================
    elif page == "📊 ダッシュボード":
        st.title("📊 学習状況ダッシュボード")
        
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
        
        # 知識ベース情報
        col1, col2 = st.columns(2)
        with col1:
            st.metric("📚 知識ベース総数", f"{stats.get('qa_total', 0)}件")
        with col2:
            st.metric("🎓 修正から学習したデータ", f"{stats.get('learned', 0)}件")
        
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
    
    # =========================================================================
    # ページ3: 学習履歴
    # =========================================================================
    elif page == "🎓 学習履歴":
        st.title("🎓 修正・学習履歴")
        st.caption("修正されたデータは自動的にRAG知識ベースに追加され、次回以降の回答生成に活用されます。")
        
        corrections = get_correction_history(session, 50)
        
        if not corrections:
            st.info("まだ学習データがありません")
        else:
            for item in corrections:
                corr_id, inq, ai_resp, corrected, notes, by, created_at = item
                with st.expander(f"🔄 #{corr_id} - {created_at} (修正者: {by})"):
                    st.markdown("**📩 元の問い合わせ**")
                    st.text(inq[:300] if inq else "")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**🤖 AI生成（修正前）**")
                        st.text_area("", value=ai_resp, height=200, key=f"ai_{corr_id}", disabled=True)
                    with col2:
                        st.markdown("**✏️ 人間による修正（学習済み）**")
                        st.text_area("", value=corrected, height=200, key=f"corr_{corr_id}", disabled=True)
                    
                    if notes:
                        st.info(f"📝 修正理由: {notes}")
    
    session.close()

if __name__ == "__main__":
    main()
