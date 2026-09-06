# Advoc AI — Legal Document Navigator & Lawyer Connect

Advoc AI is an intelligent legal assistant platform built using Django REST Framework, MongoEngine/MongoDB, React, and Google's Gemini AI. It allows users to draft, analyze, and revise legal agreements through natural conversation, run document risk summaries, and directly connect with verified legal professionals.

---

## Project Demo

▶️ **Watch the Video Demonstration on YouTube:** [https://www.youtube.com/watch?v=yzv-nw8T0xY](https://www.youtube.com/watch?v=yzv-nw8T0xY)

---

## Key Features

- **Conversational Document Generator**: Interactively build customized legal contracts, agreements, and notices using Gemini AI. Supports real-time streaming responses and signature attachment embedding.
- **Document Summarizer & Risk Analysis**: Analyze uploaded legal documents (PDF/DOCX) for potential risks, unfavorable clauses, and missing standard terms with actionable refinement recommendations.
- **Lawyer Marketplace & Consultations**: Clients can browse verified lawyer profiles filtered by legal specialization, request consultations, and schedule preferred meeting times.
- **Google Meet Integration**: Automatically generates dedicated Google Meet video call links when a lawyer accepts a consultation request.
- **Lawyer-Client Chat & Reviews**: Real-time message exchange between client and lawyer within accepted connections, including post-consultation ratings and reviews.

---

## Tech Stack

### Backend
- **Framework**: Django 5.2 & Django REST Framework (DRF)
- **Database**: MongoDB (via MongoEngine ORM) & SQLite
- **AI Models**: Google Gemini AI (`google-generativeai`)
- **Async Tasks**: Celery & Redis
- **Media Storage**: Cloudinary (for signature uploads and verification documents)

### Frontend
- **Framework**: React 18 (Vite)
- **Styling**: Tailwind CSS & Lucide Icons
- **HTTP Client**: Axios

---

## Getting Started

### Prerequisites
- Python 3.10+
- Node.js 18+
- MongoDB instance (local or MongoDB Atlas)

---

### Backend Setup

1. **Navigate to the backend directory**:
   ```bash
   cd backend
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configuration**:
   Create a `.env` file inside the `backend/` folder based on `.env.example`:
   ```env
   MONGO_URI=mongodb://localhost:27017/advoc_ai_db
   MONGO_DB_NAME=advoc_ai_db
   SECRET_KEY=your-django-secret-key
   GEMINI_API_KEY=your-gemini-api-key
   CLOUDINARY_CLOUD_NAME=your-cloudinary-name
   CLOUDINARY_API_KEY=your-cloudinary-key
   CLOUDINARY_API_SECRET=your-cloudinary-secret
   GOOGLE_CLIENT_ID=your-google-oauth-client-id
   GOOGLE_CLIENT_SECRET=your-google-oauth-client-secret
   ```

5. **Run Database Migrations & Start Server**:
   ```bash
   python manage.py migrate
   python manage.py runserver
   ```
   The backend API server will run at `http://localhost:8000`.

---

### Frontend Setup

1. **Navigate to the frontend directory**:
   ```bash
   cd frontend
   ```

2. **Install Node dependencies**:
   ```bash
   npm install
   ```

3. **Start the development server**:
   ```bash
   npm run dev
   ```
   The application will be accessible at `http://localhost:5173`.

---

## Running Tests

To execute the backend unit test suite:
```bash
cd backend
python manage.py test lawyer ai_generator
```

---

## Project Structure

```text
Advoc_Ai/
├── backend/
│   ├── ai_generator/       # Gemini AI document generation logic & views
│   ├── authentication/     # User authentication & Google OAuth handlers
│   ├── chat/               # Lawyer-client messaging & models
│   ├── document_summarizer/# Document risk analysis & clause extraction
│   ├── documents/          # Document storage & share link APIs
│   ├── lawyer/             # Profiles, connection requests & Meet link generation
│   └── legal_doc_generator/# Django project settings & URL routing
└── frontend/
    ├── src/
    │   ├── Components/     # Reusable UI elements (Navbar, Cards, Buttons)
    │   ├── pages/          # Application views (Home, Profile, Chat, Dashboard)
    │   └── api/            # Axios API config
```
