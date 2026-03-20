# Backend Codemap

## Backend Overview
- Responsibility: API server, domain logic, async conversion/publishing, and persistent product state.
- Runtime entry: `backend/config/settings.py`, `backend/config/urls.py`, `backend/manage.py`.
- Core domain center: `backend/apps/books/`.

## `config/`
- Responsibility: global framework configuration.

### `config/settings.py`
- Configures installed apps, storage strategy, middleware, DB, DRF auth/pagination, SimpleJWT cookie config, CORS/CSRF, Redis/Celery/cache.

### `config/urls.py`
- Mounts all app routes.
- Exposes `/me/books/` analytics endpoint.

### Supporting config files
- `config/celery.py`: Celery bootstrapping.
- `config/pagination.py`: shared pagination class.
- `config/serializers.py`: shared serializer utilities like date formatting.

## `apps/auth/`
- Responsibility: authentication endpoints and cookie auth integration.
- `views.py` handles register, login, refresh, me, csrf, Google login, and logout.
- `authentication.py` contains `CookieJWTAuthentication`.
- `serializers.py` validates registration and login payloads.
- This app is cohesive and security-critical.

## `apps/users/`
- Responsibility: user identity model and profile serialization.
- `models.py` defines `normalize_handle`, `UserManager`, and `User`.
- `serializers.py` contains `UserSerializer` and `ProfileSerializer`.
- `views.py` contains `ProfileView`.
- This app is slim and appropriately focused.

## `apps/books/` overview
- Responsibility: books as product, content container, reader substrate, author workflow, and publishing engine.
- Internal layering is better than the rest of the repo.

## `apps/books/models/`
- `Book`: lifecycle, visibility, extraction state, publish state, theme data, analytics.
- `BookFile`: uploaded source artifacts.
- `BookView`: per-day view analytics.
- `BookFollow`: follow relation.
- `PageNote`.
- `SavedPage`.
- `ReadingPosition`.
- `DraftImageAsset`.
- `BookAuditLog`.
- `DraftElement`.
- `ExtractedImage`.
- `Chapter`.
- `BookContent`: structured page blocks, versioning, word count.
- Supporting files:
  - `content_version.py`: content history snapshots.
  - `content_blocks.py`: typed content block structures.
  - `book_theme.py`: book theme support.
- This folder defines the real product data model.

## `apps/books/views/`
- `main.py` contains `BookViewSet`.
- Key responsibilities inside `BookViewSet`:
  - catalog visibility filtering
  - view analytics
  - upload endpoint
  - retry extraction
  - manifest endpoint
  - page endpoint
  - featured catalog
  - follow/unfollow
  - publish
  - audit
- Additional viewsets:
  - `PageNoteViewSet`
  - `SavedPageViewSet`
  - `ReadingPositionViewSet`
- `theme.py` contains book theme read/update endpoints.
- This folder contains most access-control and runtime reader behavior.

## `apps/books/serializers/`
- `main.py` contains `BookFileSerializer`, `BookSerializer`, `MyBookSerializer`, `PageNoteSerializer`, `BookAuditLogSerializer`, `SavedPageSerializer`, and `ReadingPositionSerializer`.
- `theme.py` contains theme-specific serialization.
- This folder adapts backend model shape into frontend-friendly contracts.

## `apps/books/tasks.py`
- Responsibility: async orchestration.
- Handles converter resolution and file reading from storage with retry logic.
- `process_book_upload_task` converts uploaded file into reader-ready `BookContent`.
- `process_draft_intake` runs the richer draft intake pipeline.
- `publish_book_task` handles publish background execution.
- `extract_pdf_text_task` runs deeper extraction with confidence, image extraction, and diagnostics.
- This is the most operationally complex file in the backend.

## `apps/books/services/`
- `extraction_integration.py` contains `ExtractionToContentService`.
- Creates `BookContent` from extraction.
- Links extracted images into content blocks.
- Other service files support content lifecycle abstractions.
- Good separation of business logic from web and Celery layers.

## `apps/books/publish/`
- `service.py` contains `PublishService`.
- Validates ownership, draft state, and content presence, then publishes.
- Additional files imply a broader publishing pipeline, even if the current service is simplified.

## `apps/books/extraction/`
- Responsibility: low-level extraction and analysis engine.
- Includes `engine.py`, `text_extractor.py`, `image_extractor.py`, `layout_analyzer.py`, `formatter.py`, and `confidence.py`.
- This folder is infrastructure-heavy and tightly related to import quality.

## `apps/books/converters/`
- Responsibility: source file conversion and style inference.
- Includes support for PDF/EPUB conversion plus HTML render helpers.
- Bridges raw files into structured intermediate page content.

## `apps/books/diagnostics/`
- Responsibility: capture import/extraction diagnostics.
- Supports observability for fidelity and unsupported formatting issues.

## `apps/books/audit/`
- Responsibility: audit retrieval and action recording.
- Used by the audit API action and book lifecycle tracking.

## `apps/books/validators/`
- Responsibility: validate uploaded files/images/content conditions.
- Keeps view/task code cleaner by centralizing validation rules.

## `apps/books/analytics_views.py`
- Contains `MyBooksAnalyticsView`.
- Responsibility: author dashboard feed with owner counts and analytics summary.

## `apps/library/`
- `views.py` contains `MyLibraryViewSet`, `PurchasedLibraryViewSet`, and `UserLibraryViewSet`.
- This app is query-oriented and intentionally thin.

## `apps/orders/`
- `models.py` contains `Order`.
- `views.py` contains `OrderViewSet`.
- Order creation validates book existence/published state, prevents self-purchase and duplicate purchase, checks sufficient wallet funds, then updates order records, book revenue, buyer wallet, author wallet, and transaction ledger.
- This is a clean transactional boundary.

## `apps/wallet/`
- `models.py` contains `Wallet` and `Transaction`.
- `views.py` exposes wallet stats, transactions, and deposits via `WalletViewSet`.
- `signals.py` auto-creates wallets.
- This is a compact financial subdomain.

## `apps/social/`
- `models.py` defines `Review`, `ReviewVote`, `ReviewReply`, `CommunityPost`, `CommunityPostComment`, `SavedCommunityPost`, and `CommunityPostLike`.
- `views.py` exposes `ReviewViewSet`, `CommunityPostViewSet`, `CommunityPostCommentViewSet`, and `ReviewReplyViewSet`.
- `serializers.py` contains `ReviewSerializer`, `CommunityPostCommentSerializer`, and `CommunityPostSerializer`.
- This app is feature-rich but still reasonably contained.

## Backend tests
- `apps/auth/tests/test_unit.py`: strongest auth correctness coverage.
- `apps/books/tests/test_reader_access_api.py`: validates reader access, preview/full access, cache scoping, async extraction behavior.
- `apps/books/tests/test_e2e_workflow.py`: upload -> edit -> publish -> read workflow validation.
- `pytest.ini`: standard markers and app-scoped discovery.

## Backend summary
- Best structured domain: `apps/books/`.
- Best transactional boundary: `apps/orders/`.
- Best security boundary: `apps/auth/`.
- Thinnest query facade: `apps/library/`.
- Most complex operational surface: `apps/books/tasks.py`.
