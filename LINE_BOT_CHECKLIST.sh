#!/bin/bash

# LINE Bot 部署前檢驗清單
# 使用: bash LINE_BOT_CHECKLIST.sh

set -e

echo "╔════════════════════════════════════════════════════════╗"
echo "║  LINE Bot 系統 - 部署前檢驗清單                        ║"
echo "║  更新日期: 2025-01-31                                  ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

FAILED=0
PASSED=0

check_pass() {
    echo "✅ $1"
    ((PASSED++))
}

check_fail() {
    echo "❌ $1"
    ((FAILED++))
}

check_warn() {
    echo "⚠️  $1"
}

# ============ 1. 環境檢查 ============
echo "┌─ 1. 環境檢查"
echo ""

# 檢查 Python
if command -v python3 &> /dev/null; then
    PY_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
    check_pass "Python 3 已安裝 (版本: $PY_VERSION)"
else
    check_fail "Python 3 未安裝"
fi

# 檢查 pip
if command -v pip3 &> /dev/null; then
    check_pass "pip3 已安裝"
else
    check_fail "pip3 未安裝"
fi

# 檢查 git
if command -v git &> /dev/null; then
    check_pass "git 已安裝"
else
    check_fail "git 未安裝"
fi

echo ""

# ============ 2. 依賴檢查 ============
echo "┌─ 2. Python 依賴檢查"
echo ""

REQUIRED_PACKAGES=(
    "flask"
    "linebot"
    "requests"
    "python-dotenv"
    "gunicorn"
)

for package in "${REQUIRED_PACKAGES[@]}"; do
    if python3 -c "import $package" 2>/dev/null; then
        check_pass "$package 已安裝"
    else
        check_fail "$package 未安裝"
        check_warn "  請運行: pip install -r requirements.txt"
    fi
done

echo ""

# ============ 3. 檔案檢查 ============
echo "┌─ 3. 必需檔案檢查"
echo ""

FILES=(
    "line_bot.py"
    "line_webhook.py"
    ".env.example"
    "Procfile"
    "docker-compose.yml"
    "requirements.txt"
    "docs/SETUP_LINE_BOT.md"
    "docs/DEPLOYMENT_GUIDE.md"
    "docs/TESTING_GUIDE.md"
    "docs/LINE_BOT_SUMMARY.md"
)

for file in "${FILES[@]}"; do
    if [[ -f "$file" ]]; then
        check_pass "檔案存在: $file"
    else
        check_fail "檔案缺失: $file"
    fi
done

echo ""

# ============ 4. 代碼質量檢查 ============
echo "┌─ 4. 代碼質量檢查"
echo ""

# 檢查 line_bot.py 的類定義
if grep -q "class FeedbackManager" line_bot.py; then
    check_pass "FeedbackManager 類已定義"
else
    check_fail "FeedbackManager 類未定義"
fi

if grep -q "class ValidationManager" line_bot.py; then
    check_pass "ValidationManager 類已定義"
else
    check_fail "ValidationManager 類未定義"
fi

if grep -q "class GitHubIssueManager" line_bot.py; then
    check_pass "GitHubIssueManager 類已定義"
else
    check_fail "GitHubIssueManager 類未定義"
fi

# 檢查 line_webhook.py 的 Flask 應用
if grep -q "@app.route" line_webhook.py; then
    check_pass "Flask 路由已定義"
else
    check_fail "Flask 路由未定義"
fi

if grep -q "/webhook" line_webhook.py; then
    check_pass "/webhook 端點已定義"
else
    check_fail "/webhook 端點未定義"
fi

if grep -q "/health" line_webhook.py; then
    check_pass "/health 端點已定義"
else
    check_fail "/health 端點未定義"
fi

if grep -q "/feedback/stats" line_webhook.py; then
    check_pass "/feedback/stats 端點已定義"
else
    check_fail "/feedback/stats 端點未定義"
fi

echo ""

# ============ 5. 配置檢查 ============
echo "┌─ 5. 配置檢查"
echo ""

if [[ -f ".env" ]]; then
    check_pass ".env 配置文件存在"
    
    # 檢查必需的環境變數
    ENV_VARS=(
        "LINE_CHANNEL_SECRET"
        "LINE_CHANNEL_ACCESS_TOKEN"
        "GITHUB_TOKEN"
        "GITHUB_REPO"
    )
    
    for var in "${ENV_VARS[@]}"; do
        if grep -q "^$var=" .env; then
            VALUE=$(grep "^$var=" .env | cut -d'=' -f2)
            if [[ -n "$VALUE" && "$VALUE" != "your_"* && "$VALUE" != "your-"* ]]; then
                check_pass "$var 已配置"
            else
                check_warn "$var 未設置或為默認值"
            fi
        else
            check_warn "$var 配置缺失"
        fi
    done
else
    check_fail ".env 配置文件缺失"
    check_warn "請運行: cp .env.example .env 並編輯"
fi

echo ""

# ============ 6. 文檔檢查 ============
echo "┌─ 6. 文檔完整性檢查"
echo ""

DOCS=(
    "docs/SETUP_LINE_BOT.md"
    "docs/DEPLOYMENT_GUIDE.md"
    "docs/TESTING_GUIDE.md"
    "docs/LINE_BOT_SUMMARY.md"
    "docs/LINE_BOT_QUICK_REFERENCE.md"
)

for doc in "${DOCS[@]}"; do
    if [[ -f "$doc" ]]; then
        LINES=$(wc -l < "$doc")
        if [[ $LINES -gt 50 ]]; then
            check_pass "文檔完整: $doc ($LINES 行)"
        else
            check_warn "文檔可能不完整: $doc ($LINES 行)"
        fi
    else
        check_warn "文檔缺失: $doc"
    fi
done

echo ""

# ============ 7. 數據目錄檢查 ============
echo "┌─ 7. 數據目錄檢查"
echo ""

if [[ -d "data" ]]; then
    check_pass "data 目錄存在"
    
    if [[ -w "data" ]]; then
        check_pass "data 目錄可寫入"
    else
        check_fail "data 目錄不可寫入"
    fi
else
    check_fail "data 目錄不存在"
    check_warn "請運行: mkdir -p data"
fi

echo ""

# ============ 8. Git 檢查 ============
echo "┌─ 8. Git 配置檢查"
echo ""

if [[ -f ".gitignore" ]]; then
    if grep -q "\.env$" .gitignore; then
        check_pass ".env 已添加到 .gitignore"
    else
        check_warn ".env 未添加到 .gitignore (建議添加)"
    fi
    
    if grep -q "line_feedback.json" .gitignore; then
        check_pass "line_feedback.json 已添加到 .gitignore"
    else
        check_warn "line_feedback.json 未添加到 .gitignore"
    fi
else
    check_warn ".gitignore 不存在"
fi

echo ""

# ============ 9. 部署就緒檢查 ============
echo "┌─ 9. 部署就緒檢查"
echo ""

# Heroku
if [[ -f "Procfile" ]]; then
    if grep -q "gunicorn" Procfile; then
        check_pass "Heroku Procfile 已配置"
    else
        check_fail "Procfile 配置不正確"
    fi
else
    check_fail "Procfile 缺失"
fi

# Docker
if [[ -f "docker-compose.yml" ]]; then
    if grep -q "linebot:" docker-compose.yml; then
        check_pass "Docker Compose 已配置"
    else
        check_fail "docker-compose.yml 配置不正確"
    fi
else
    check_fail "docker-compose.yml 缺失"
fi

if [[ -f "Dockerfile" ]]; then
    check_pass "Dockerfile 存在"
else
    check_warn "Dockerfile 不存在 (可選)"
fi

echo ""

# ============ 10. 安全性檢查 ============
echo "┌─ 10. 安全性檢查"
echo ""

# 檢查是否在 git 中提交了 .env
if git ls-files | grep -q "\.env$"; then
    check_fail ".env 已提交到 git (安全風險!)"
else
    check_pass ".env 未提交到 git"
fi

# 檢查 requirements.txt 是否包含安全相關的包
if grep -q "python-dotenv" requirements.txt; then
    check_pass "python-dotenv 已添加 (環境變數安全)"
else
    check_fail "python-dotenv 未添加"
fi

# 檢查敏感詞過濾
if grep -q "SENSITIVE_WORDS" line_bot.py; then
    check_pass "敏感詞過濾已實現"
else
    check_fail "敏感詞過濾未實現"
fi

# 檢查速率限制
if grep -q "RATE_LIMIT" line_bot.py; then
    check_pass "速率限制已實現"
else
    check_fail "速率限制未實現"
fi

echo ""

# ============ 摘要 ============
echo "╔════════════════════════════════════════════════════════╗"
echo "║                      檢驗結果摘要                       ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

TOTAL=$((PASSED + FAILED))
PERCENTAGE=$((PASSED * 100 / TOTAL))

echo "通過檢查: $PASSED/$TOTAL ($PERCENTAGE%)"
echo ""

if [[ $FAILED -eq 0 ]]; then
    echo "🎉 所有檢查通過！系統已準備好部署。"
    echo ""
    echo "後續步驟:"
    echo "1. ✅ 已檢查環境和依賴"
    echo "2. ✅ 已驗證所有必需檔案"
    echo "3. ✅ 已檢查代碼質量"
    echo "4. 接下來: 運行測試套件"
    echo "   bash docs/TESTING_GUIDE.md"
    echo "5. 然後: 選擇部署方式"
    echo "   - Heroku: git push heroku main"
    echo "   - Docker: docker-compose up -d"
    echo "   - 本地: python line_webhook.py"
    echo ""
    exit 0
else
    echo "⚠️  發現 $FAILED 個問題需要修復"
    echo ""
    echo "建議:"
    echo "1. 查看上面標記的失敗項"
    echo "2. 按照建議進行修正"
    echo "3. 重新運行此檢驗: bash LINE_BOT_CHECKLIST.sh"
    echo ""
    exit 1
fi
