# Purchase Order Management System (POMS)

A modern desktop-based Purchase Order Management System developed using **Python, PyQt5, SQLite, OpenPyXL, and ReportLab**. The application streamlines supplier management, purchase order processing, reporting, and analytics through an intuitive graphical interface.

---

## Overview

The Purchase Order Management System (POMS) is designed to automate and simplify procurement workflows within small and medium-sized organizations. It enables users to manage suppliers, create and track purchase orders, monitor order statuses, and generate professional reports.

The application follows a modular architecture with separation of concerns between:

* User Interface Layer (PyQt5)
* Business Logic Layer
* Data Access Layer (SQLite)
* Reporting Layer (Excel/PDF Export)

---

## Key Features

### Supplier Management Module

Manage supplier information efficiently.

#### Features

* Create supplier records
* Update supplier details
* Delete suppliers with dependency checks
* GSTIN validation
* Email validation
* Phone number validation
* Searchable supplier database

#### Supplier Information Stored

* Supplier Name
* GSTIN Number
* Email Address
* Phone Number
* Business Address

---

### Purchase Order Management Module

Comprehensive purchase order lifecycle management.

#### Features

* Create purchase orders
* Edit existing orders
* Delete orders
* Assign suppliers
* Add multiple order items
* Automatic order total calculation
* Notes and remarks support
* Order status tracking

#### Purchase Order Status Workflow

Pending → Approved → Received

or

Pending → Cancelled

---

### Dynamic Item Management

Each purchase order can contain multiple line items.

#### Item Information

* Product Description
* Quantity
* Unit Price
* Calculated Amount

#### Advanced Features

* Real-time calculations
* Numeric input validation
* Automatic grand total updates
* Row insertion/removal

---

### Analytics Dashboard

Provides real-time business insights.

#### Dashboard Metrics

* Total Purchase Orders
* Total Suppliers
* Pending Orders
* Total Procurement Value

#### Additional Components

* Pending Order Progress Indicator
* Recent Purchase Orders Table
* Status-Based Visualization

---

### Reporting & Export System

Generate business-ready reports.

#### Excel Export

Export all purchase orders to Microsoft Excel.

Features:

* Structured worksheets
* Formatted headers
* Numeric formatting
* Professional tabular layout

#### PDF Report Generation

Generate printable PDF reports containing:

* Order Summary
* Supplier Information
* Status Information
* Procurement Statistics
* Financial Totals

---

## Technical Architecture

### Architecture Pattern

```text
Presentation Layer (PyQt5 GUI)
            │
            ▼
Business Logic Layer
            │
            ▼
Data Access Layer (SQLite)
            │
            ▼
Reporting Layer
(OpenPyXL / ReportLab)
```

---

## Technology Stack

| Category       | Technology          |
| -------------- | ------------------- |
| Language       | Python 3.x          |
| GUI Framework  | PyQt5               |
| Database       | SQLite3             |
| Excel Export   | OpenPyXL            |
| PDF Generation | ReportLab           |
| Validation     | Regex               |
| Data Storage   | Relational Database |

---

## Database Design

### Entity Relationship Diagram

```text
Suppliers
    │
    │ 1
    │
    ▼
Purchase Orders
    │
    │ 1
    │
    ▼
Purchase Order Items
```

---

### Suppliers Table

```sql
CREATE TABLE suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    gstin TEXT UNIQUE,
    email TEXT,
    phone TEXT,
    address TEXT
);
```

---

### Purchase Orders Table

```sql
CREATE TABLE purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number TEXT UNIQUE NOT NULL,
    supplier_id INTEGER NOT NULL,
    order_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL,
    notes TEXT,
    total REAL DEFAULT 0,
    FOREIGN KEY (supplier_id)
    REFERENCES suppliers(id)
);
```

---

### Purchase Order Items Table

```sql
CREATE TABLE po_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit_price REAL NOT NULL,
    FOREIGN KEY (po_id)
    REFERENCES purchase_orders(id)
    ON DELETE CASCADE
);
```

---

## Installation Guide

### Prerequisites

* Python 3.9+
* pip package manager

---

### Clone Repository

```bash
git clone https://github.com/username/PurchaseOrderManagementSystem.git
cd PurchaseOrderManagementSystem
```

---

### Create Virtual Environment

```bash
python -m venv venv
```

Activate:

Windows

```bash
venv\Scripts\activate
```

Linux/Mac

```bash
source venv/bin/activate
```

---

### Install Dependencies

```bash
pip install PyQt5
pip install openpyxl
pip install reportlab
```

or

```bash
pip install -r requirements.txt
```

---

## Running the Application

```bash
python main.py
```

Upon first execution:

* SQLite database is automatically created.
* Required tables are generated automatically.
* Application dashboard is initialized.

---

## Input Validation Strategy

### GSTIN Validation

Regex-based validation ensures compliance with Indian GST standards.

Example:

```text
22AAAAA0000A1Z5
```

---

### Email Validation

RFC-compliant email structure validation.

Example:

```text
supplier@company.com
```

---

### Phone Validation

Constraints:

* Numeric only
* Minimum 7 digits
* Maximum 15 digits

---

## Performance Optimizations

Implemented optimizations include:

* SQLite indexing through primary keys
* Lazy loading of records
* Efficient table refresh mechanisms
* Automatic transaction handling
* Cascading deletion support
* Connection pooling pattern through helper methods

---

## Security Considerations

### Database Security

* Parameterized SQL Queries
* SQL Injection Prevention
* Foreign Key Constraints
* Data Integrity Validation

### Input Security

* Regular Expression Validation
* Numeric Validators
* Length Restrictions
* Type Validation

---

## User Interface Design

### Design Philosophy

The application adopts a modern dark-themed interface focusing on:

* High readability
* Minimal visual clutter
* Improved productivity
* Enterprise-style dashboards

### UI Components

* Dashboard Cards
* Interactive Tables
* Date Pickers
* Progress Indicators
* Dynamic Forms
* Export Toolbars

---

## Future Roadmap

### Version 2.0

Planned enhancements:

* User Authentication System
* Role-Based Access Control (RBAC)
* Inventory Management
* Vendor Rating System
* Purchase Approval Workflow
* Email Notifications
* Multi-User Environment
* MySQL/PostgreSQL Support
* REST API Integration
* Cloud Database Deployment
* Data Backup & Restore
* Audit Logging

---

## Testing

The application has been tested for:

* CRUD Operations
* Database Transactions
* Validation Logic
* Export Functionality
* UI Responsiveness
* Error Handling

---

## Learning Outcomes

This project demonstrates practical implementation of:

* Desktop Application Development
* Object-Oriented Programming
* Relational Database Design
* GUI Development
* Report Generation
* Data Validation
* Software Architecture Principles
* Database Connectivity
* Enterprise Application Design

---

## Author

### Soumyadeep Basu

Software Developer | Python Developer | Desktop Application Developer

---

## License

MIT License

Copyright (c) 2026 Soumyadeep Basu

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files to deal in the Software without restriction.
