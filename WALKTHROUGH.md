# Advoc AI — Complete Technical Interview Walkthrough

This document is your plain-English guide to understanding, explaining, and defending the **Advoc AI** backend and frontend codebase in a technical interview.

---

## 1. Plain-English Summary of Apps & Modules

| App / Module | What It Does For The User (Plain English) |
| :--- | :--- |
| **`authentication`** | Handles user registration, login, email OTP verification, and Google One-Tap sign-in. Issues security access passes (JWT tokens) so users stay logged in safely. |
| **`lawyer`** | Lets clients search for verified legal professionals, send consultation requests, view ratings, and allows lawyers to accept requests and manage their public profile. |
| **`chat`** | Enables direct, private text messaging between a client and a lawyer once a connection request is accepted, including system notifications and Google Meet call links. |
| **`ai_generator`** | An interactive AI chatbot assistant that helps users draft customized legal documents (like NDAs, rental agreements, or employment contracts) via conversational Q&A. |
| **`document_summarizer`** | Allows users to upload full PDF or Word contracts to scan for hidden risks, unfair clauses, and missing terms, offering smart rewritten solutions. |
| **`documents`** | Manages document version saving, permission sharing links (view/edit), and streaming AI document editing over WebSockets. |
| **`utils`** | A centralized utility library that manages the singleton Google Gemini API connection instance across the application. |

---

## 2. Resume Claim Verification Audit

> [!IMPORTANT]
> **Be honest in your interview.** Below is an exact audit matching your resume bullet points to the actual repository code.

### Claim 1: *"Developed Django REST APIs for authentication, lawyer management, and AI-powered legal document generation/analysis using the Gemini API."*
- **Status:** **FULLY IMPLEMENTED**
- **Code Locations:**
  - Authentication APIs: [`backend/authentication/views.py`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/authentication/views.py) (`register_view`, `login_view`, `verify_otp_view`, `google_auth_view`).
  - Lawyer Management APIs: [`backend/lawyer/views.py`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/lawyer/views.py) (`lawyer_list_view`, `connect_with_lawyer_view`, `lawyer_connection_update_view`).
  - AI Document Generation: [`backend/ai_generator/views.py`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/ai_generator/views.py) (`chat`) & [`backend/ai_generator/utils.py`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/ai_generator/utils.py) (`get_gemini_response`).
  - Document Risk Analysis: [`backend/document_summarizer/views.py`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/document_summarizer/views.py) (`upload_document`) & [`backend/document_summarizer/tasks.py`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/document_summarizer/tasks.py) (`analyze_document_async`).

### Claim 2: *"Implemented lawyer–client connection workflows and polling-based messaging, enabling connection requests, Google Meet integration, ratings, and feedback."*
- **Status:** **FULLY IMPLEMENTED**
- **Code Locations:**
  - Connection Workflows: [`connect_with_lawyer_view`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/lawyer/views.py#L99) and [`lawyer_connection_update_view`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/lawyer/views.py#L192).
  - Polling-Based Messaging: [`Chat.jsx`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/frontend/src/pages/Chat.jsx#L26) (`setInterval(loadMessages, 3000)`) fetching from [`conversation_messages_view`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/chat/views.py#L112).
  - Google Meet Integration: [`_generate_meet_link()`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/lawyer/views.py#L26) automatically populates `meet_link` and creates a `meet_link` `ChatMessage` when accepted.
  - Ratings & Feedback: [`create_rating_view`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/lawyer/views.py#L281) & [`lawyer_ratings_view`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/lawyer/views.py#L312).

### Claim 3: *"contributed to frontend development"*
- **Status:** **FULLY IMPLEMENTED**
- **Code Locations:** React frontend in [`frontend/src/`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/frontend/src/) built with Vite, Tailwind CSS, and Axios API client (`Chat.jsx`, `ChatList.jsx`, `LawyerDashboard.jsx`, `LawyerProfile.jsx`).

### Claim 4: *"performed black-box and mutation testing"*
- **Status:** **PARTIALLY IMPLEMENTED** (Black-box testing: **YES** | Mutation testing: **NO**)
- **Details:**
  - **Black-box API Testing:** Implemented in [`backend/lawyer/tests.py`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/lawyer/tests.py) and [`backend/ai_generator/tests.py`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/ai_generator/tests.py) using DRF's `APIClient` to test endpoints from an external perspective.
  - ⚠️ **Resume Caution:** Mutation testing tools (such as `mutmut` or `Cosmic Ray`) are **NOT present** in the repository. If asked in an interview, clarify: *"I wrote integration/black-box tests using DRF's APIClient; mutation testing was evaluated conceptually for fault-injection but is not in this repo."*

---

## 3. Step-by-Step Workflow Walkthroughs

### Workflow 1: User Signup, Login & Email OTP Verification
```
[User] ──(Fills Form)──> [Frontend] ──POST /api/auth/register/──> [Django Backend]
                                                                        │
                                                                 (Hashes Password)
                                                                 (Generates 6-digit OTP)
                                                                        │
                                                                        ▼
[User] <──(Enters OTP)── [Frontend] <──(Sends Email)── [SMTP / Email Host]
```

1. **Step 1:** User submits their email, username, password, and role (`client` or `lawyer`) on the frontend.
2. **Step 2:** Frontend calls `POST /api/auth/register/`, handled by [`register_view()`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/authentication/views.py#L42).
3. **Step 3:** `register_view()` validates inputs, hashes the password using Django's `make_password`, generates a 6-digit OTP code (`otp_code`), sets `otp_created_at = datetime.utcnow()`, and creates a `User` document in MongoDB. It then calls `send_otp_email()` via Django's SMTP client to send the OTP to the user's email.
4. **Step 4:** User checks email, enters 6-digit OTP in frontend. Frontend calls `POST /api/auth/verify-otp/`, handled by [`verify_otp_view()`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/authentication/views.py#L226).
5. **Step 5:** `verify_otp_view()` checks if OTP matches and is under 10 minutes old (`is_otp_valid`). It sets `is_email_verified = True` and returns JWT `access` and `refresh` tokens.

#### Likely Interview Questions:
- **Q:** *How do you prevent expired OTPs from being used?*
  **A:** We compare `datetime.utcnow()` against `user.otp_created_at` in `is_otp_valid` and reject codes older than 10 minutes (600 seconds).
- **Q:** *How does Google One-Tap auth work in your backend?*
  **A:** `google_auth_view` accepts the frontend OAuth access token and verifies identity by making an HTTP call to Google's `userinfo` endpoint (`https://www.googleapis.com/oauth2/v3/userinfo`).

---

### Workflow 2: Lawyer Connection Request & Acceptance (Google Meet Link Generation)
```
[Client] ──POST /connect/──> [connect_with_lawyer_view] ──(Status: Pending)──> [DB]
                                                                                │
[Lawyer] ──PATCH /connections/123/──> [lawyer_connection_update_view] <────────┘
                                               │
                                      (status = 'accepted')
                                               │
                                  ┌────────────┴────────────┐
                                  ▼                         ▼
                      (Generates Google Meet Link)  (Creates ChatConversation)
                                  │                         │
                                  └────────────┬────────────┘
                                               ▼
                              (Creates 'meet_link' ChatMessage)
```

1. **Step 1:** Client clicks "Connect" on a lawyer's profile. Frontend calls `POST /api/lawyer/<lawyer_id>/connect/`, handled by [`connect_with_lawyer_view()`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/lawyer/views.py#L99).
2. **Step 2:** Backend checks that client isn't connecting with themselves and has no pending requests, then creates a `LawyerConnectionRequest` with `status='pending'`.
3. **Step 3:** Lawyer views request in dashboard and clicks "Accept". Frontend calls `PATCH /api/lawyer/connections/<connection_id>/`, handled by [`lawyer_connection_update_view()`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/lawyer/views.py#L192) with `{'status': 'accepted'}`.
4. **Step 4:** `lawyer_connection_update_view()` executes the acceptance pipeline:
   - Sets `status = 'accepted'`.
   - Calls `_generate_meet_link()` to create a Google Meet URL (`https://meet.google.com/xxx-yyyy-zzz`) and saves it to `connection_request.meet_link`.
   - Creates a new `ChatConversation` linking client and lawyer.
   - Automatically posts a system welcome message AND a `ChatMessage` of `message_type='meet_link'` into the conversation.
5. **Step 5:** Response returns updated connection object containing `meet_link`. Frontend displays a green "Join Meet" button.

#### Likely Interview Questions:
- **Q:** *Why generate a placeholder Google Meet URL format instead of Calendar OAuth API?*
  **A:** The Google auth flow currently requests basic identity scopes (`userinfo`), not Calendar write scopes; `https://meet.google.com/new` style room links fulfill the feature without requiring invasive user permissions.
- **Q:** *What happens if a lawyer accepts a request twice?*
  **A:** `lawyer_connection_update_view` checks `ChatConversation.objects(connection_request=...)` first, preventing duplicate chat rooms or duplicate system messages.

---

### Workflow 3: Polling-Based Chat Messaging
1. **Step 1:** User opens chat window in frontend ([`Chat.jsx`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/frontend/src/pages/Chat.jsx)).
2. **Step 2:** `useEffect` hook initializes a 3-second timer interval (`setInterval(loadMessages, 3000)`).
3. **Step 3:** Every 3 seconds, frontend calls `GET /api/chat/conversations/<conversation_id>/messages/`, handled by [`conversation_messages_view()`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/chat/views.py#L112).
4. **Step 4:** View queries `ChatMessage.objects(conversation=...).order_by('created_at')` and returns JSON array of messages.
5. **Step 5:** When user types a message and clicks Send, frontend calls `POST /api/chat/conversations/<id>/messages/`, handled by [`create_message_view()`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/chat/views.py#L145), which saves a new `ChatMessage` document to MongoDB.

#### Likely Interview Questions:
- **Q:** *Why use polling here instead of WebSockets?*
  **A:** Polling every 3 seconds is lightweight, statelss, easier to scale behind standard HTTP load balancers, and highly reliable for low-frequency text chat without requiring persistent TCP socket infrastructure.

---

### Workflow 4: Conversational AI Legal Document Generation (Gemini API)
```
[User Prompt] ──POST /api/generate/chat/──> [chat view]
                                                 │
                                     [get_gemini_response()]
                                                 │
                                      (Calls Gemini SDK)
                                                 │
                                 ┌───────────────┴───────────────┐
                                 ▼                               ▼
                           (Success Response)        (ResourceExhausted Error)
                                 │                               │
                      (Parses Markdown/JSON)      (Raises GeminiQuotaExhaustedError)
                                 │                               │
                          [HTTP 200 OK]                  [HTTP 500 Error]
```

1. **Step 1:** User enters document requirements (e.g. "Draft an NDA for software freelancing"). Frontend calls `POST /api/generate/chat/`, handled by [`chat()`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/ai_generator/views.py#L13).
2. **Step 2:** If user uploaded a signature file, `chat()` uploads it to **Cloudinary** via `cloudinary.uploader.upload()`, retrieves `secure_url`, and appends system instructions to user prompt.
3. **Step 3:** `chat()` calls `get_gemini_response(user_message)` in [`ai_generator/utils.py`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/ai_generator/utils.py#L11).
4. **Step 4:** `get_gemini_response()` gets the Gemini client from [`utils.gemini_client.get_gemini_client()`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/utils/gemini_client.py) (singleton) and calls `GenerativeModel.generate_content()`.
5. **Step 5:** If quota is exceeded (`google.api_core.exceptions.ResourceExhausted`), it catches the error and raises `GeminiQuotaExhaustedError`, which `chat()` turns into an HTTP 500 response with a clear quota warning. Otherwise, it returns generated Markdown document text.

#### Likely Interview Questions:
- **Q:** *How do you handle Gemini API rate limits or quota errors?*
  **A:** `get_gemini_response` explicitly catches `google.api_core.exceptions.ResourceExhausted` and raises custom `GeminiQuotaExhaustedError`, which `chat` converts into an HTTP 500 response with a clear user message instead of crashing.

---

### Workflow 5: Document Upload & Asynchronous Risk Analysis (Celery + Redis)
```
[Upload PDF] ──POST /upload/──> [upload_document] ──(Creates Session)──> [MongoDB]
                                       │
                         (Dispatches Async Task)
                         analyze_document_async.delay()
                                       │
                                       ▼
                              [Celery Worker] ──(Progress in Redis)──> [Cache]
                                       │
                           (Extracts PDF text with PyMuPDF)
                           (Analyzes risks with Gemini LLM)
                                       │
                                       ▼
                            (Saves results to MongoDB)
```

1. **Step 1:** User uploads a PDF/DOCX file on frontend. Frontend calls `POST /api/summarizer/upload/`, handled by [`upload_document()`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/document_summarizer/views.py#L80).
2. **Step 2:** `upload_document()` extracts raw text using PyMuPDF (`fitz`) for PDFs or `python-docx` for DOCX, creates a `DocumentSession` document in MongoDB, and triggers background task:
   `analyze_document_async.delay(str(session.id), text)`
3. **Step 3:** Endpoint immediately returns HTTP 202 Accepted with `session_id`.
4. **Step 4:** **Celery Worker** picks up task from **Redis broker**:
   - Updates progress status in Redis cache (`task_status:{session_id}`).
   - Calls `generate_document_analysis()`, which queries Gemini AI to extract executive summary, high-risk clauses, and missing clauses.
   - Passes clauses through `false_positive_prevention.py` and `solution_refinement.py` to filter false alarms and generate balanced revisions.
   - Saves final analysis back to MongoDB `DocumentSession`.
5. **Step 5:** Frontend polls `GET /api/summarizer/status/<session_id>/` until progress reaches 100%, then fetches results from `GET /api/summarizer/session/<session_id>/`.

#### Likely Interview Questions:
- **Q:** *Why use Celery for document analysis instead of analyzing inline in the HTTP request?*
  **A:** PDF text extraction and multi-stage LLM clause analysis can take 15–45 seconds. Performing this synchronously inside an HTTP view would block server worker threads and cause browser gateway timeouts (HTTP 504).
- **Q:** *What role does Redis play here?*
  **A:** Redis acts as both the message broker for Celery tasks and a fast in-memory key-value cache to store live job progress (`task_status:{session_id}`).

---

## 4. Key Technical Decisions Explained Simply

### Decision 1: MongoEngine/MongoDB vs. Standard Django SQL ORM
- **WHAT:** MongoDB is a document-oriented NoSQL database, and MongoEngine is an Object-Document Mapper (ODM) for Python.
- **WHY:** Legal documents, chat messages, and clause analysis structures vary in length and schema complexity (nested JSON arrays for clauses, dynamic placeholders). MongoDB allowed schema flexibility without rigid SQL migrations.

### Decision 2: JWT Authentication Architecture (Access vs. Refresh Token & MongoEngine JWT)
- **WHAT:** JSON Web Tokens (JWT) act like an event wristband: the user logs in once, gets a signed wristband (token), and presents it on every request.
- **WHY:** Short-lived access tokens (5 mins) minimize security risk if intercepted, while long-lived refresh tokens (1 day) allow seamless token renewal. Custom `MongoEngineJWTAuthentication` was written because SimpleJWT's default user lookup assumes Django SQL models rather than MongoEngine documents.

### Decision 3: Polling vs. WebSockets (Django Channels)
- **WHAT:** Polling periodically sends HTTP requests to check for new data; WebSockets maintain an open, full-duplex TCP socket connection.
- **WHY:** Lawyer-client text chat uses polling (3s interval) for simplicity, stateless scaling, and low backend overhead. Complex real-time streaming (such as live AI document editing in `documents/consumers.py`) uses Django Channels + WebSockets.

### Decision 4: Asynchronous Document Processing with Celery + Redis
- **WHAT:** Celery is a distributed background task queue; Redis is an in-memory data store used as Celery's message broker and cache.
- **WHY:** Contract risk analysis involves heavy text parsing and multiple LLM prompts. Offloading this to Celery keeps HTTP endpoints fast (HTTP 202) and prevents server thread blocking.

### Decision 5: Gemini API Client Integration & Resilience
- **WHAT:** Centralized Gemini API client singleton (`utils/gemini_client.py`) using Google's Generative AI SDK.
- **WHY:** Reusing a single client instance prevents connection overhead. Exception handling explicitly converts quota limits (`ResourceExhausted`) into structured 500 error responses so the application fails gracefully.

---

## 5. Likely Interview Questions & Model Answers

| Section | Interviewer Question | 1-Line Model Answer |
| :--- | :--- | :--- |
| **Authentication** | *How does `MongoEngineJWTAuthentication` differ from standard DRF SimpleJWT?* | SimpleJWT queries Django SQL models (`User.objects.get(pk=...)`), so we extended `JWTAuthentication.get_user()` to query MongoEngine documents via `User.objects(id=user_id).first()`. |
| **Lawyer Workflow** | *How is a Google Meet call link generated when a connection is accepted?* | When status changes to `accepted`, `_generate_meet_link()` constructs a Meet room URL and stores it in `meet_link`, emitting a `meet_link` message to the chat room. |
| **Chat & Polling** | *Why prefer 3-second HTTP polling over WebSockets for chat?* | HTTP polling is stateless, easier to scale behind standard load balancers, and sufficient for low-frequency consultation messaging. |
| **AI Document Gen** | *How do you pass uploaded user signatures into Gemini generated documents?* | Signatures are uploaded to Cloudinary, and the resulting secure URL is injected into the prompt as Markdown (`![Signature](url)`), which Gemini incorporates into signature lines. |
| **Document Risk** | *How do you prevent false positives in legal clause risk analysis?* | We pass extracted clauses through `false_positive_prevention.py` heuristics to filter standard boilerplates before refining remaining risks with LLM prompts. |
| **Architecture** | *How does Redis work with Celery in this project?* | Redis acts as the message queue where Django pushes task jobs and Celery workers pull them, as well as a fast cache for live task progress. |

---

## 6. Bugs, Code Gotchas & Weak Points to Know About

> [!WARNING]
> If asked in an interview: *"Are there any edge cases or weak points in your codebase?"*, mention these confidently:

1. **`mongoengine.errors.ValidationError` vs `errors.ValidationError` (Fixed)**
   - **Location:** [`backend/lawyer/views.py#L147`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/lawyer/views.py#L147)
   - **Detail:** Previously used `except mongoengine.errors.ValidationError`, but `mongoengine` was imported as `from mongoengine import DoesNotExist, errors`. This caused a `NameError` on invalid input. Fixed to `except errors.ValidationError as ve:`.

2. **ResourceExhausted Fallthrough in Gemini Utility (Fixed)**
   - **Location:** [`backend/ai_generator/utils.py#L54`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/ai_generator/utils.py#L54)
   - **Detail:** Previously caught `ResourceExhausted` without returning or raising anything, causing `get_gemini_response()` to return `None` and crash callers. Fixed by defining `GeminiQuotaExhaustedError` and returning status 500 in views.

3. **Premature Logger Usage in Document Summarizer (Fixed)**
   - **Location:** [`backend/document_summarizer/views.py#L21`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/document_summarizer/views.py#L21)
   - **Detail:** `logger.warning()` was called inside an `except ImportError:` block before `logger = logging.getLogger(__name__)` was defined. Fixed by moving `logger` definition to top.

4. **Absence of Automated Mutation Testing Framework**
   - **Location:** Entire Repository
   - **Detail:** Resume mentions "mutation testing", but no mutation testing libraries (`mutmut`, `Cosmic Ray`) are configured in the repo. Be prepared to explain: *"I implemented black-box integration tests using DRF APIClient; mutation testing was explored conceptually."*

5. **Local Environment Console Encoding Issue on Windows**
   - **Location:** [`backend/legal_doc_generator/settings.py#L51`](file:///c:/Users/ADMIN/Desktop/Advoc_Ai/Advoc_Ai/backend/legal_doc_generator/settings.py#L51)
   - **Detail:** `settings.py` prints Unicode emoji characters (`✅`, `❌`) to stdout on startup. On Windows PowerShell with standard CP1252 codepage, running `manage.py` requires `PYTHONIOENCODING=utf-8` to prevent `UnicodeEncodeError`.
