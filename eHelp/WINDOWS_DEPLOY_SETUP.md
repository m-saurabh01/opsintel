# eHelp - Offline Windows Deployment Guide

## Prerequisites
- **Minimum**: 2 GB RAM, 500 MB disk space
- **Recommended**: 4 GB RAM, 2 GB disk space
- Windows Server 2016 or later (or Windows 10/11 Pro)
- Administrator rights for Windows Service installation

## Package Contents
- `ehelp-backend-standalone.exe` (PyInstaller-bundled backend)
- `ehelp-frontend-dist.zip` (production-optimized build)
- `ehelp-seed-db.sqlite` (pre-indexed sample documents)
- `install-service.bat` (Windows Service installer)
- `config-prod.ini` (production configuration)

## Setup Steps

### 1. Extract the Deployment Package
```batch
cd C:\Program Files\ehelp
# Extract: windows-deploy-portable.zip
```

### 2. Install as Windows Service
```batch
cd C:\Program Files\ehelp
install-service.bat
```

This registers `eHelpService` to start automatically at boot.

### 3. Start the Service
```batch
# Via Services Manager:
# Win + R → services.msc → Find "eHelp Service" → Start

# Or via Command Prompt (Admin):
net start eHelpService
```

### 4. Verify Installation
- Open `http://localhost:8123` in Chrome
- Expect: eHelp home page with sample documents

### 5. Configure (Optional)
Edit `config-prod.ini`:
```ini
[server]
port = 8123
workers = 4

[database]
path = C:\ProgramData\ehelp\data.sqlite

[ai]
enabled = 0
ollama_url = http://localhost:11434
```

Then restart:
```batch
net stop eHelpService
net start eHelpService
```

## Production Settings

### Database Backup
```batch
# Daily backup (add to Task Scheduler):
xcopy "C:\ProgramData\ehelp\*.sqlite" "C:\backups\ehelp\%date:~-4,4%%date:~-10,2%%date:~-7,2%\" /Y
```

### Log Files
- Location: `C:\ProgramData\ehelp\logs\`
- Rotation: Daily, kept for 30 days (auto-managed)

### Performance
- **Uvicorn Workers**: 4 (tune based on CPU cores)
- **Max Concurrent Users**: ~1000 per worker (4000 total)
- **Database Pool Size**: 10 connections

### Offline Document Upload
1. Place files in `C:\ProgramData\ehelp\inbox\`
2. Admin → Upload Documents → Browse Inbox
3. Set Category and click Upload

## Uninstall
```batch
net stop eHelpService
sc delete eHelpService
rmdir /s "C:\Program Files\ehelp"
rmdir /s "C:\ProgramData\ehelp"
```

## Troubleshooting

### Service Won't Start
1. Check logs: `C:\ProgramData\ehelp\logs\error.log`
2. Verify port 8123 is free: `netstat -ano | findstr :8123`
3. Ensure admin rights for installation

### "No Documents Found"
- Seed database not initialized
- Run: `ehelp-backend-standalone.exe --init-db`

### High Memory Usage
- Reduce workers in `config-prod.ini`
- Clear browser cache: `Ctrl + Shift + Delete`

## Security Hardening

### Firewall (Allow Only Trusted IPs)
```batch
netsh advfirewall firewall add rule name="eHelp" dir=in action=allow program="C:\Program Files\ehelp\ehelp-backend-standalone.exe" profile=any localip=10.0.0.0/8
```

### HTTPS (Reverse Proxy)
Use Nginx/Apache in front with SSL:
```nginx
server {
    listen 443 ssl http2;
    server_name ehelp.example.com;
    ssl_certificate /etc/ssl/ehelp.crt;
    ssl_certificate_key /etc/ssl/ehelp.key;
    location / {
        proxy_pass http://localhost:8123;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## Load Balancing (For 2000+ Concurrent Users)
1. Deploy 2-3 instances on separate machines
2. Use Windows Server NLB (Network Load Balancing)
3. Shared database (upgrade to PostgreSQL for concurrency)
4. Shared file storage (NFS or SMB)

## Monitoring
- Task Manager: Monitor CPU, Memory, Disk I/O
- Performance Monitor: `perfmon.msc` → Add counters for python.exe
- Event Viewer: `eventvwr.msc` → Application logs
