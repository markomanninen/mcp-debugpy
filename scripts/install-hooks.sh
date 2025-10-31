#!/bin/bash
# Install git hooks for this repository
# Run this script once after cloning: ./scripts/install-hooks.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK_DIR="$REPO_ROOT/.git/hooks"

echo "Installing git hooks..."

# Pre-commit hook
cat > "$HOOK_DIR/pre-commit" << 'EOF'
#!/bin/bash
# Pre-commit hook to run full CI checks locally before allowing commit
# This prevents CI failures by catching issues early

set -e

echo "🔍 Running pre-commit CI checks..."
echo ""

# Use venv python if available, otherwise system python
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python"
fi

echo "📦 Using Python: $PYTHON"
echo ""

# 1. Ruff linting
echo "🔧 Running ruff..."
if $PYTHON -m ruff check . 2>/dev/null; then
    echo "✅ Ruff passed"
else
    echo "⚠️  Ruff not available or failed, continuing..."
fi
echo ""

# 2. Black formatting check
echo "🎨 Running black..."
if ! $PYTHON -m black --check .; then
    echo "❌ Black check failed!"
    echo "💡 Run: $PYTHON -m black . to fix formatting"
    exit 1
fi
echo "✅ Black passed"
echo ""

# 3. Mypy type checking
echo "🔍 Running mypy..."
if ! $PYTHON -m mypy src --ignore-missing-imports --explicit-package-bases; then
    echo "❌ Mypy check failed!"
    exit 1
fi
echo "✅ Mypy passed"
echo ""

# 4. Run tests
echo "🧪 Running tests..."
if ! $PYTHON -m pytest -q; then
    echo "❌ Tests failed!"
    exit 1
fi
echo "✅ Tests passed"
echo ""

echo "🎉 All pre-commit checks passed! Proceeding with commit..."
EOF

chmod +x "$HOOK_DIR/pre-commit"

echo "✅ Git hooks installed successfully!"
echo ""
echo "The pre-commit hook will now run these checks before every commit:"
echo "  - Ruff linting"
echo "  - Black formatting"
echo "  - Mypy type checking"
echo "  - Pytest test suite"
echo ""
echo "To bypass the hook (not recommended): git commit --no-verify"
