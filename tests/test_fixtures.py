"""Unit tests for Reddit Scraper formatting and validation logic.

Tests formatting functions and input validation using saved JSON fixtures
from real Reddit API responses. No network required.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import (
    ScraperInput,
    ScrapingMode,
    format_comment_from_json,
    format_post_from_json,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict:
    path = FIXTURE_DIR / name
    with open(path) as f:
        return json.load(f)


class TestPostFormatting:
    """Post formatting from JSON listing data."""

    def test_format_post_has_all_required_fields(self):
        data = load_fixture("sample_post.json")
        post = format_post_from_json(data)

        required = ["id", "subreddit", "title", "author", "score", "url", "created"]
        for field in required:
            assert field in post, f"Missing required field: {field}"
            assert post[field] != "", f"Empty required field: {field}"

        assert post["type"] == "post"
        assert isinstance(post["score"], int)
        assert isinstance(post["numComments"], int)
        assert isinstance(post["isNSFW"], bool)

    def test_format_post_deleted_author(self):
        data = load_fixture("sample_post.json")
        data["author"] = "[deleted]"
        post = format_post_from_json(data)
        assert post["author"] == "[deleted]"

    def test_format_post_new_fields(self):
        data = load_fixture("sample_post.json")
        data["upvote_ratio"] = 0.89
        data["edited"] = 1740850000
        data["post_hint"] = "link"
        data["is_original_content"] = True
        data["author_flair_text"] = "Expert"
        data["crosspost_parent"] = "t3_xyz789"
        data["media_only"] = False
        data["is_gallery"] = False
        post = format_post_from_json(data)
        assert post["upvoteRatio"] == 0.89
        assert post["edited"] == 1740850000
        assert post["postHint"] == "link"
        assert post["isOriginalContent"] is True
        assert post["authorFlair"] == "Expert"
        assert post["crosspostParent"] == "t3_xyz789"
        assert post["mediaOnly"] is False
        assert post["isGallery"] is False

    def test_format_post_edited_false_when_missing(self):
        data = load_fixture("sample_post.json")
        data["edited"] = False
        post = format_post_from_json(data)
        assert post["edited"] is False

    def test_format_post_thumbnail_filtering(self):
        data = load_fixture("sample_post.json")
        # Sentinels should become empty string
        for sentinel in ("self", "default", "nsfw", "spoiler", ""):
            data["thumbnail"] = sentinel
            post = format_post_from_json(data)
            assert post["thumbnail"] == "", f"Sentinel '{sentinel}' not filtered"

        # Real URLs should pass through
        data["thumbnail"] = "https://example.com/thumb.jpg"
        post = format_post_from_json(data)
        assert post["thumbnail"] == "https://example.com/thumb.jpg"


class TestCommentFormatting:
    """Comment formatting from JSON listing data."""

    def test_format_comment_has_all_required_fields(self):
        data = load_fixture("sample_comment.json")
        comment = format_comment_from_json(data)

        required = ["id", "author", "body", "score", "url", "created"]
        for field in required:
            assert field in comment, f"Missing required field: {field}"

        assert comment["type"] == "comment"
        assert isinstance(comment["score"], int)
        assert isinstance(comment["depth"], int)
        assert isinstance(comment["isSubmitter"], bool)

    def test_format_comment_depth_propagation(self):
        data = load_fixture("sample_comment.json")
        comment = format_comment_from_json(data, depth=3)
        assert comment["depth"] == 3

    def test_format_comment_postid_extraction(self):
        data = load_fixture("sample_comment.json")
        data["link_id"] = "t3_abc123"
        comment = format_comment_from_json(data)
        assert comment["postId"] == "abc123"

    def test_format_comment_deleted_body(self):
        data = load_fixture("sample_comment.json")
        data["body"] = ""
        comment = format_comment_from_json(data)
        assert comment["body"] == "[deleted]"


class TestInputValidation:
    """Input validation logic."""

    def test_valid_subreddit_posts_mode(self):
        config = ScraperInput(
            mode=ScrapingMode.SUBREDDIT_POSTS,
            subreddits=["python"],
        )
        assert config.validate_for_mode() is None

    def test_missing_subreddit_posts_returns_error(self):
        config = ScraperInput(mode=ScrapingMode.SUBREDDIT_POSTS)
        error = config.validate_for_mode()
        assert error is not None
        assert "subreddit" in error.lower()

    def test_missing_search_query_returns_error(self):
        config = ScraperInput(mode=ScrapingMode.SEARCH)
        error = config.validate_for_mode()
        assert error is not None
        assert "search" in error.lower()

    def test_valid_search_with_query(self):
        config = ScraperInput(
            mode=ScrapingMode.SEARCH,
            search_query="python tutorial",
        )
        assert config.validate_for_mode() is None

    def test_valid_search_with_queries_list(self):
        config = ScraperInput(
            mode=ScrapingMode.SEARCH,
            search_queries_list=["python", "javascript"],
        )
        assert config.validate_for_mode() is None

    def test_missing_usernames_returns_error(self):
        config = ScraperInput(mode=ScrapingMode.USER_PROFILE)
        error = config.validate_for_mode()
        assert error is not None
        assert "username" in error.lower()

    def test_valid_user_profile(self):
        config = ScraperInput(
            mode=ScrapingMode.USER_PROFILE,
            usernames=["spez"],
        )
        assert config.validate_for_mode() is None

    def test_missing_post_urls_returns_error(self):
        config = ScraperInput(mode=ScrapingMode.POST_COMMENTS)
        error = config.validate_for_mode()
        assert error is not None
        assert "post" in error.lower()

    def test_valid_post_comments(self):
        config = ScraperInput(
            mode=ScrapingMode.POST_COMMENTS,
            post_urls=["https://www.reddit.com/r/python/comments/abc123/test/"],
        )
        assert config.validate_for_mode() is None

    def test_default_mode_is_subreddit_posts(self):
        config = ScraperInput()
        assert config.mode == ScrapingMode.SUBREDDIT_POSTS

    def test_default_max_results(self):
        config = ScraperInput()
        assert config.max_results == 100

    def test_subreddit_r_prefix_cleaning(self):
        config = ScraperInput(
            mode=ScrapingMode.SUBREDDIT_POSTS,
            subreddits=["r/python", "r/javascript"],
        )
        assert config.subreddits == ["python", "javascript"]

    def test_username_u_prefix_cleaning(self):
        config = ScraperInput(
            mode=ScrapingMode.USER_PROFILE,
            usernames=["u/spez", "u/kn0thing"],
        )
        assert config.usernames == ["spez", "kn0thing"]


class TestFromActorInput:
    """Mapping from raw Apify input to ScraperInput."""

    def test_full_input_mapping(self):
        raw = {
            "mode": "search",
            "searchQuery": "test query",
            "searchSort": "top",
            "maxResults": 500,
            "includeComments": True,
        }
        config = ScraperInput.from_actor_input(raw)
        assert config.mode == ScrapingMode.SEARCH
        assert config.search_query == "test query"
        assert config.search_sort.value == "top"
        assert config.max_results == 500
        assert config.include_comments is True

    def test_empty_input_uses_defaults(self):
        config = ScraperInput.from_actor_input({})
        assert config.mode == ScrapingMode.SUBREDDIT_POSTS
        assert config.max_results == 100
        assert config.include_comments is False