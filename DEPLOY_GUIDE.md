# BRIM CS システム - デプロイガイド (Streamlit Cloud + Supabase)

## 📋 前提条件

✅ Supabaseプロジェクトが作成済み
✅ Claude APIキーを取得済み
✅ GitHubアカウントがある
✅ Streamlit Cloudアカウントがある（無料）

---

## 🚀 デプロイ手順

### ステップ1: GitHubリポジトリを作成

1. GitHubにログイン
2. **New repository** をクリック
3. リポジトリ名: `brim-cs-system`
4. **Public** を選択（Privateでも可）
5. **Create repository** をクリック

---

### ステップ2: ファイルをGitHubにアップロード

#### 方法A: GitHub Web UIで直接アップロード（簡単）

1. GitHubのリポジトリページで **Add file** → **Upload files** をクリック
2. 以下のファイルをドラッグ&ドロップ:
   - `streamlit_app_supabase.py`
   - `brim_product_database.json`
   - `requirements_supabase.txt` → **`requirements.txt`にリネーム**
3. **Commit changes** をクリック

#### 方法B: コマンドライン（Mac）

```bash
cd ~/Desktop/BRIM_CS

# Gitリポジトリを初期化
git init
git add streamlit_app_supabase.py
git add brim_product_database.json
git add requirements_supabase.txt

# requirements.txtにリネーム
mv requirements_supabase.txt requirements.txt
git add requirements.txt

# コミット
git commit -m "Initial commit"

# GitHubにプッシュ
git remote add origin https://github.com/YOUR-USERNAME/brim-cs-system.git
git branch -M main
git push -u origin main
```

---

### ステップ3: Streamlit Cloudでデプロイ

1. https://share.streamlit.io にアクセス
2. **New app** をクリック
3. 以下を入力:
   - **Repository**: `YOUR-USERNAME/brim-cs-system`
   - **Branch**: `main`
   - **Main file path**: `streamlit_app_supabase.py`
4. **Advanced settings...** をクリック

---

### ステップ4: 環境変数（Secrets）を設定

**Advanced settings** の **Secrets** セクションに以下を入力:

```toml
DATABASE_URL = "postgresql://postgres:[YOUR-PASSWORD]@db.xxxxx.supabase.co:5432/postgres"

CLAUDE_API_KEY = "sk-ant-xxxxx"
```

**重要:**
- `DATABASE_URL`: Supabaseの接続文字列（パスワード含む）
- `CLAUDE_API_KEY`: AnthropicのAPIキー

---

### ステップ5: デプロイ

1. **Deploy!** ボタンをクリック
2. 数分待つ（初回は5-10分かかることがあります）
3. デプロイ完了！

---

## 🌐 アクセス

デプロイが完了すると、以下のようなURLが発行されます：

```
https://brim-cs-system-xxxxx.streamlit.app
```

このURLを社内メンバーに共有すれば、誰でもアクセス可能です！

---

## 🔐 アクセス制限（オプション）

Streamlit Cloudの無料プランでは認証機能がありません。

アクセス制限が必要な場合：
1. GitHubリポジトリをPrivateにする
2. Streamlit CloudでBasic Auth（有料プラン）を使用
3. VPN経由でのみアクセス可能にする

---

## 🛠️ トラブルシューティング

### エラー: "Module not found"
→ `requirements.txt` が正しくアップロードされているか確認

### エラー: "DATABASE_URL not set"
→ Streamlit Cloudの **Settings** → **Secrets** で環境変数を設定

### エラー: "Connection refused"
→ Supabaseの接続文字列が正しいか確認
→ パスワードが含まれているか確認

### アプリが起動しない
→ Streamlit Cloudの **Logs** を確認してエラーメッセージを見る

---

## 📝 更新方法

ファイルを更新したい場合：

1. GitHubのリポジトリでファイルを編集
2. **Commit changes**
3. Streamlit Cloudが自動的に再デプロイ

---

## 💰 料金

**完全無料**（制限内）:
- Streamlit Cloud: 無料プラン（Public apps: 無制限）
- Supabase: 無料プラン（500MB DB、5GB転送/月）

---

## 🎉 完了！

デプロイが成功すれば、社内の誰でもブラウザからアクセスできます！

---

作成日: 2026-02-23
