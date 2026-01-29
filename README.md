# PyTalk - Multi-Tenant Video Meeting Application

A modern, multi-tenant video conferencing application built with Django and WebRTC, similar to Google Meet.

## Features

- **Multi-Tenant Architecture**: Organizations can have their own isolated workspace
- Real-time video and audio communication using WebRTC
- Screen sharing
- Meeting recording (captures all participants)
- In-meeting chat
- Collaborative whiteboard
- User authentication (login/register)
- Schedule meetings
- Host approval for joining meetings
- Organization management (create, invite members, manage roles)
- Modern dark theme UI

## Tech Stack

- **Backend**: Django 4.2 + Django Channels (WebSocket)
- **Database**: PostgreSQL (multi-tenant)
- **Frontend**: HTML, CSS, JavaScript
- **Real-time**: WebSockets via Django Channels
- **Video/Audio**: WebRTC with PeerJS

## Multi-Tenant Architecture

PyTalk uses a shared database with tenant isolation approach:

- **Organizations**: Each organization (tenant) is a separate workspace
- **Memberships**: Users can belong to multiple organizations with different roles (Owner, Admin, Member)
- **Data Isolation**: Meetings and data are scoped to organizations
- **Role-Based Access**: Organization owners and admins can manage settings and invite members

## Project Structure

```
gmeet-clone-main/
├── backend/
│   ├── manage.py
│   ├── requirements.txt
│   ├── gmeet/                  # Django project settings
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── asgi.py
│   ├── users/                  # User & Organization app
│   │   ├── models.py           # Organization, Membership, Profile
│   │   ├── views.py
│   │   ├── urls.py
│   │   ├── forms.py
│   │   └── middleware.py       # Tenant middleware
│   ├── meetings/               # Meetings app
│   │   ├── models.py           # Meeting, Recording
│   │   ├── views.py
│   │   ├── urls.py
│   │   ├── consumers.py        # WebSocket handlers
│   │   └── routing.py
│   ├── templates/              # Django templates
│   └── static/                 # CSS, JS, images
├── .gitignore
└── README.md
```

## Installation

### Prerequisites

- Python 3.8+
- PostgreSQL 12+
- pip

### Database Setup

1. **Create PostgreSQL database**
   ```sql
   CREATE DATABASE "PyTalk";
   ```

### Application Setup

1. **Navigate to the backend directory**
   ```bash
   cd backend
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv

   # Windows
   venv\Scripts\activate

   # Linux/Mac
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**

   Edit `.env` file in the `backend/` directory:
   ```env
   DB_NAME=PyTalk
   DB_USER=postgres
   DB_PASSWORD=admin
   DB_HOST=localhost
   DB_PORT=5432
   ```

5. **Run database migrations**
   ```bash
   python manage.py migrate
   ```

6. **Create a superuser (optional)**
   ```bash
   python manage.py createsuperuser
   ```

7. **Start the development server**
   ```bash
   python manage.py runserver 3000
   ```

8. **Open in browser**
   ```
   http://localhost:3000
   ```

## Configuration

### Environment Variables

Create a `.env` file in the `backend/` directory:

```env
# Django Settings
SECRET_KEY=your-secret-key-change-in-production
DEBUG=True

# PostgreSQL Database
DB_NAME=PyTalk
DB_USER=postgres
DB_PASSWORD=admin
DB_HOST=localhost
DB_PORT=5432

# Email settings (optional)
MAIL_USER=your-email@gmail.com
MAIL_PASS=your-app-password
```

## Usage

### Getting Started

1. **Register** a new account (creates a personal organization automatically)
2. **Create an organization** or use your personal workspace
3. **Invite team members** to your organization
4. **Schedule meetings** within your organization
5. **Share meeting links** with participants

### Organization Management

- **Switch Organizations**: Use the dropdown in the navbar
- **Create Organization**: Add new workspaces for different teams
- **Invite Members**: Add users by username with role assignment
- **Manage Settings**: Update organization name and member roles

### Meeting Controls

- **Video**: Toggle camera on/off
- **Microphone**: Toggle audio on/off
- **Screen Share**: Share your screen with participants
- **Record**: Record the meeting (downloads as .webm file)
- **Chat**: Send messages to all participants
- **Whiteboard**: Collaborate on a shared whiteboard
- **Leave**: Exit the meeting

## API Endpoints

### Authentication
- `POST /user/register/` - Register new user
- `POST /user/login/` - Login
- `GET /user/logout/` - Logout

### Organizations
- `GET /user/organizations/` - List user's organizations
- `POST /user/organizations/create/` - Create organization
- `GET /user/organizations/<id>/switch/` - Switch organization
- `GET /user/organizations/<id>/settings/` - Organization settings
- `POST /user/organizations/<id>/invite/` - Invite member

### Meetings
- `GET /meeting/meetings/` - List meetings
- `POST /meeting/schedule/` - Schedule meeting
- `GET /meeting/meetingdetails/<room_id>/` - Meeting details
- `GET /meeting/startmeeting/<room_id>/` - Join meeting

## License

MIT License
