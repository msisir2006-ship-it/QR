# Attendance Management System

A Flask-based web application for managing student attendance using QR codes.

## Features

- Admin login system
- QR code generation for attendance marking
- Student attendance scanning
- View and manage attendance records
- Export attendance data to CSV
- Backup functionality
- Subject and branch filtering

## Local Development

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the application:
   ```bash
   python app1.py
   ```

3. Open http://localhost:5000 in your browser

## Deployment

### Vercel Deployment

1. Push this code to a GitHub repository
2. Connect your GitHub repo to Vercel
3. Vercel will automatically detect the Python app and deploy it
4. The app will be available at your Vercel domain

### GitHub Setup

1. Create a new repository on GitHub
2. Initialize git in your local directory:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/yourusername/yourrepo.git
   git push -u origin main
   ```

## Database

The application uses SQLite database. On Vercel, the database is stored in `/tmp` which is ephemeral. For production use with persistent data, consider using a cloud database service.