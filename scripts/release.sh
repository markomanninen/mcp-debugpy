#!/usr/bin/env bash
set -euo pipefail

# Release automation script for mcp-debugpy
# Usage: ./scripts/release.sh [patch|minor|major]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Print colored message
print_msg() {
    local color=$1
    shift
    echo -e "${color}$*${NC}"
}

print_error() { print_msg "$RED" "ERROR: $*"; }
print_success() { print_msg "$GREEN" "✓ $*"; }
print_info() { print_msg "$YELLOW" "→ $*"; }

# Check if we're in the right directory
if [[ ! -f "$ROOT_DIR/pyproject.toml" ]]; then
    print_error "Must be run from mcp-debugpy repository root or scripts directory"
    exit 1
fi

cd "$ROOT_DIR"

# Detect Python and ensure venv exists
if [[ ! -d "$VENV_DIR" ]]; then
    print_error "Virtual environment not found at $VENV_DIR"
    print_info "Run: python -m venv .venv && .venv/bin/pip install -e '.[dev]'"
    exit 1
fi

PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

if [[ ! -x "$PYTHON" ]]; then
    print_error "Python executable not found: $PYTHON"
    exit 1
fi

# Ensure required packages are installed
print_info "Checking required packages..."
for pkg in black pytest; do
    if ! "$PYTHON" -c "import $pkg" 2>/dev/null; then
        print_info "Installing $pkg..."
        "$PIP" install -q "$pkg"
    fi
done
print_success "Required packages available"

# Get version bump type (default: patch)
BUMP_TYPE="${1:-patch}"
if [[ ! "$BUMP_TYPE" =~ ^(patch|minor|major)$ ]]; then
    print_error "Invalid version bump type: $BUMP_TYPE"
    print_info "Usage: $0 [patch|minor|major]"
    exit 1
fi

# Get current version from pyproject.toml
CURRENT_VERSION=$(grep '^version = ' pyproject.toml | cut -d'"' -f2)
print_info "Current version: $CURRENT_VERSION"

# Calculate new version
IFS='.' read -r major minor patch <<< "$CURRENT_VERSION"
case "$BUMP_TYPE" in
    major) NEW_VERSION="$((major + 1)).0.0" ;;
    minor) NEW_VERSION="${major}.$((minor + 1)).0" ;;
    patch) NEW_VERSION="${major}.${minor}.$((patch + 1))" ;;
esac

print_info "New version will be: $NEW_VERSION"
read -p "Continue? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_info "Cancelled"
    exit 0
fi

# Check git status
if [[ -n $(git status --porcelain) ]]; then
    print_error "Working directory is not clean. Commit or stash changes first."
    git status --short
    exit 1
fi
print_success "Working directory is clean"

# Ensure we're on main branch
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    print_error "Must be on main branch (currently on: $CURRENT_BRANCH)"
    exit 1
fi
print_success "On main branch"

# Pull latest changes
print_info "Pulling latest changes..."
git pull origin main
print_success "Up to date with origin"

# Run tests
print_info "Running tests..."
export PYTHONPATH="$ROOT_DIR:$ROOT_DIR/src:${PYTHONPATH:-}"
if ! "$PYTHON" -m pytest tests/ -v --tb=short; then
    print_error "Tests failed!"
    exit 1
fi
print_success "All tests passed"

# Format code with Black
print_info "Formatting code with Black..."
"$PYTHON" -m black src/ tests/ scripts/ || true
print_success "Code formatted"

# Update version in pyproject.toml
print_info "Updating version to $NEW_VERSION..."
sed -i.bak "s/^version = \".*\"/version = \"$NEW_VERSION\"/" pyproject.toml
rm -f pyproject.toml.bak
print_success "Version updated in pyproject.toml"

# Commit version bump
git add pyproject.toml
if [[ -n $(git status --porcelain) ]]; then
    git add -A
    git commit -m "chore: Bump version to $NEW_VERSION

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
    print_success "Version bump committed"
else
    print_info "No changes to commit"
fi

# Create and push tag
print_info "Creating tag v$NEW_VERSION..."
git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION"
print_success "Tag created"

# Push changes and tag
print_info "Pushing to origin..."
git push origin main
git push origin "v$NEW_VERSION"
print_success "Pushed to origin"

# Create GitHub release (if gh is available)
if command -v gh &> /dev/null; then
    print_info "Creating GitHub release..."
    
    # Generate release notes
    PREV_TAG=$(git describe --tags --abbrev=0 "v$NEW_VERSION^" 2>/dev/null || echo "")
    if [[ -n "$PREV_TAG" ]]; then
        CHANGELOG_URL="https://github.com/markomanninen/mcp-debugpy/compare/${PREV_TAG}...v${NEW_VERSION}"
    else
        CHANGELOG_URL="https://github.com/markomanninen/mcp-debugpy/commits/v${NEW_VERSION}"
    fi
    
    RELEASE_NOTES="## v$NEW_VERSION

$(git log "${PREV_TAG}..HEAD" --pretty=format:"- %s" 2>/dev/null | grep -v "^- chore: Bump version" || echo "- Release v$NEW_VERSION")

**Full Changelog**: $CHANGELOG_URL"
    
    gh release create "v$NEW_VERSION" \
        --title "v$NEW_VERSION" \
        --notes "$RELEASE_NOTES"
    
    print_success "GitHub release created: https://github.com/markomanninen/mcp-debugpy/releases/tag/v$NEW_VERSION"
else
    print_info "gh CLI not found - skipping GitHub release creation"
    print_info "Create release manually at: https://github.com/markomanninen/mcp-debugpy/releases/new?tag=v$NEW_VERSION"
fi

print_success "Release v$NEW_VERSION completed!"
print_info "Next steps:"
print_info "  1. Verify release at: https://github.com/markomanninen/mcp-debugpy/releases"
print_info "  2. Monitor CI: https://github.com/markomanninen/mcp-debugpy/actions"
