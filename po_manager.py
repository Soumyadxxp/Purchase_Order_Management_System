#!/usr/bin/env python3
"""
Purchase Order Management System – Enterprise Edition
-----------------------------------------------------
A single‑file desktop application built with Python, PyQt5 and SQLAlchemy.

Features:
  * Full CRUD for suppliers and purchase orders
  * Indian Rupee (₹) currency
  * Robust validation (email, GSTIN, phone, date constraints)
  * Duplicate PO number prevention
  * Editable item table with inline decimal validation and Delete‑key removal
  * Dashboard with key metrics
  * Asynchronous DB operations (UI stays responsive)
  * Logging to file and console
  * Configurable via config.json (fallback to defaults)
  * SQLAlchemy ORM – easy migration to PostgreSQL / MySQL
  * Audit fields (created_at, updated_at) for traceability

The application works with a single .py file and a SQLite .db file created automatically.
"""

import sys
import os
import json
import logging
import re
from datetime import datetime, date
from threading import Lock
from functools import wraps

# --------------------------------------------------------------------------- #
#  Third‑party imports
# --------------------------------------------------------------------------- #
from PyQt5.QtCore import (
    Qt, QRegExp, QDate, QThread, pyqtSignal, QTimer, QSettings
)
from PyQt5.QtGui import QRegExpValidator, QDoubleValidator, QFont, QColor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QComboBox, QDateEdit, QTextEdit, QMessageBox, QHeaderView,
    QAbstractItemView, QFrame, QSizePolicy, QStyledItemDelegate, QDialog,
    QDialogButtonBox, QProgressBar, QStatusBar
)

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, ForeignKey,
    DateTime, Text, func, UniqueConstraint, Index, event
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.pool import StaticPool

# --------------------------------------------------------------------------- #
#  Configuration (with fallback)
# --------------------------------------------------------------------------- #
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "database": {
        "url": "sqlite:///po_manager.db",
        "echo": False,
        "pool_size": 5,
        "max_overflow": 10
    },
    "logging": {
        "level": "INFO",
        "file": "po_manager.log",
        "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    },
    "app": {
        "title": "Purchase Order Management System",
        "window_width": 1200,
        "window_height": 800,
        "currency": "\u20b9"  # ₹
    }
}


def load_config():
    """Load configuration from JSON file; create with defaults if missing."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        # merge with defaults (deep merge not needed for top-level keys)
        for key, value in DEFAULT_CONFIG.items():
            if key not in user_config:
                user_config[key] = value
        return user_config
    else:
        # write default config for next run
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return DEFAULT_CONFIG


CONFIG = load_config()
RUPEE = CONFIG["app"]["currency"]

# --------------------------------------------------------------------------- #
#  Logging setup
# --------------------------------------------------------------------------- #
LOG_LEVEL = getattr(logging, CONFIG["logging"]["level"].upper(), logging.INFO)
LOG_FILE = CONFIG["logging"]["file"]
LOG_FORMAT = CONFIG["logging"]["format"]

logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("po_manager")

# --------------------------------------------------------------------------- #
#  Database ORM (SQLAlchemy)
# --------------------------------------------------------------------------- #
Base = declarative_base()


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    gstin = Column(String(15), unique=True, nullable=True, index=True)
    email = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=True)
    address = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    purchase_orders = relationship("PurchaseOrder", back_populates="supplier", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Supplier(id={self.id}, name='{self.name}')>"


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("po_number", name="uq_po_number"),
        Index("idx_po_supplier", "supplier_id"),
        Index("idx_po_order_date", "order_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    po_number = Column(String(50), nullable=False, unique=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False)
    order_date = Column(DateTime, nullable=False)
    due_date = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, default="Pending")
    notes = Column(Text, nullable=True)
    total = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    supplier = relationship("Supplier", back_populates="purchase_orders")
    items = relationship("POItem", back_populates="purchase_order", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PurchaseOrder(id={self.id}, po_number='{self.po_number}')>"


class POItem(Base):
    __tablename__ = "po_items"
    __table_args__ = (
        Index("idx_item_po", "po_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    po_id = Column(Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    description = Column(String(200), nullable=False)
    quantity = Column(Float, nullable=False, default=1.0)
    unit_price = Column(Float, nullable=False, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    purchase_order = relationship("PurchaseOrder", back_populates="items")

    def __repr__(self):
        return f"<POItem(id={self.id}, description='{self.description}')>"


# --------------------------------------------------------------------------- #
#  Database engine & session
# --------------------------------------------------------------------------- #
DB_URL = CONFIG["database"]["url"]
ECHO = CONFIG["database"]["echo"]

# For SQLite, we need to enable foreign key constraints
if DB_URL.startswith("sqlite"):
    engine = create_engine(
        DB_URL,
        echo=ECHO,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
else:
    engine = create_engine(
        DB_URL,
        echo=ECHO,
        pool_size=CONFIG["database"].get("pool_size", 5),
        max_overflow=CONFIG["database"].get("max_overflow", 10),
    )

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db_session():
    """Return a new SQLAlchemy session."""
    return SessionLocal()


# Create tables if they don't exist
Base.metadata.create_all(bind=engine)
logger.info("Database tables verified/created.")

# --------------------------------------------------------------------------- #
#  Threading utilities for async DB operations
# --------------------------------------------------------------------------- #
class DbWorker(QThread):
    """Background thread to run database operations without blocking the UI."""
    finished = pyqtSignal(object)  # result (or exception)
    error = pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.func(*self.args, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            logger.exception("Database operation failed")
            self.error.emit(str(e))


# --------------------------------------------------------------------------- #
#  Helper functions & validators
# --------------------------------------------------------------------------- #
def fmt_money(value):
    """Format a number as Indian Rupee currency."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = 0.0
    return f"{RUPEE} {value:,.2f}"


def parse_date(qdate):
    """Convert QDate to string 'YYYY-MM-DD'."""
    return qdate.toString("yyyy-MM-dd")


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


def validate_email(email):
    return bool(EMAIL_RE.match(email)) if email else True


def validate_gstin(gstin):
    return bool(GSTIN_RE.match(gstin)) if gstin else True


def validate_phone(phone):
    return phone.isdigit() and 7 <= len(phone) <= 15 if phone else True


# --------------------------------------------------------------------------- #
#  Service layer (business logic)
# --------------------------------------------------------------------------- #
class SupplierService:
    @staticmethod
    def add_supplier(session, name, gstin, email, phone, address):
        try:
            supplier = Supplier(
                name=name.strip(),
                gstin=gstin.strip().upper() if gstin else None,
                email=email.strip() if email else None,
                phone=phone.strip() if phone else None,
                address=address.strip() if address else None
            )
            session.add(supplier)
            session.commit()
            logger.info(f"Added supplier: {supplier.name} (id={supplier.id})")
            return supplier
        except IntegrityError as e:
            session.rollback()
            if "gstin" in str(e).lower():
                raise ValueError("GSTIN must be unique.")
            raise
        except Exception as e:
            session.rollback()
            logger.exception("Error adding supplier")
            raise

    @staticmethod
    def update_supplier(session, supplier_id, name, gstin, email, phone, address):
        supplier = session.query(Supplier).filter(Supplier.id == supplier_id).first()
        if not supplier:
            raise ValueError("Supplier not found")
        try:
            supplier.name = name.strip()
            supplier.gstin = gstin.strip().upper() if gstin else None
            supplier.email = email.strip() if email else None
            supplier.phone = phone.strip() if phone else None
            supplier.address = address.strip() if address else None
            session.commit()
            logger.info(f"Updated supplier id={supplier_id}")
            return supplier
        except IntegrityError as e:
            session.rollback()
            if "gstin" in str(e).lower():
                raise ValueError("GSTIN must be unique.")
            raise
        except Exception as e:
            session.rollback()
            logger.exception("Error updating supplier")
            raise

    @staticmethod
    def delete_supplier(session, supplier_id):
        supplier = session.query(Supplier).filter(Supplier.id == supplier_id).first()
        if not supplier:
            raise ValueError("Supplier not found")
        # check if referenced by any PO (foreign key with RESTRICT)
        po_count = session.query(PurchaseOrder).filter(PurchaseOrder.supplier_id == supplier_id).count()
        if po_count > 0:
            raise ValueError("Cannot delete supplier with existing purchase orders.")
        try:
            session.delete(supplier)
            session.commit()
            logger.info(f"Deleted supplier id={supplier_id}")
        except Exception as e:
            session.rollback()
            logger.exception("Error deleting supplier")
            raise

    @staticmethod
    def list_suppliers(session):
        return session.query(Supplier).order_by(Supplier.name).all()

    @staticmethod
    def get_supplier(session, supplier_id):
        return session.query(Supplier).filter(Supplier.id == supplier_id).first()


class PurchaseOrderService:
    @staticmethod
    def po_number_exists(session, po_number, exclude_id=None):
        query = session.query(PurchaseOrder).filter(PurchaseOrder.po_number == po_number)
        if exclude_id:
            query = query.filter(PurchaseOrder.id != exclude_id)
        return query.first() is not None

    @staticmethod
    def add_po(session, po_number, supplier_id, order_date, due_date, status, notes, items):
        # items: list of (description, quantity, unit_price)
        # Validate
        if not po_number.strip():
            raise ValueError("PO number is required")
        if PurchaseOrderService.po_number_exists(session, po_number):
            raise ValueError(f"PO number '{po_number}' already exists.")
        if not items:
            raise ValueError("At least one item is required.")

        # Compute total
        total = sum(qty * price for _, qty, price in items)

        try:
            po = PurchaseOrder(
                po_number=po_number.strip(),
                supplier_id=supplier_id,
                order_date=order_date,
                due_date=due_date,
                status=status,
                notes=notes.strip() if notes else None,
                total=total
            )
            session.add(po)
            session.flush()  # to get po.id

            for desc, qty, price in items:
                item = POItem(
                    po_id=po.id,
                    description=desc.strip(),
                    quantity=qty,
                    unit_price=price
                )
                session.add(item)

            session.commit()
            logger.info(f"Added PO: {po.po_number} (id={po.id})")
            return po
        except Exception as e:
            session.rollback()
            logger.exception("Error adding purchase order")
            raise

    @staticmethod
    def update_po(session, po_id, po_number, supplier_id, order_date, due_date, status, notes, items):
        po = session.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
        if not po:
            raise ValueError("Purchase order not found")

        if po_number.strip() != po.po_number and PurchaseOrderService.po_number_exists(session, po_number, exclude_id=po_id):
            raise ValueError(f"PO number '{po_number}' already exists.")
        if not items:
            raise ValueError("At least one item is required.")

        total = sum(qty * price for _, qty, price in items)

        try:
            po.po_number = po_number.strip()
            po.supplier_id = supplier_id
            po.order_date = order_date
            po.due_date = due_date
            po.status = status
            po.notes = notes.strip() if notes else None
            po.total = total

            # Replace items
            session.query(POItem).filter(POItem.po_id == po_id).delete()
            for desc, qty, price in items:
                item = POItem(
                    po_id=po.id,
                    description=desc.strip(),
                    quantity=qty,
                    unit_price=price
                )
                session.add(item)

            session.commit()
            logger.info(f"Updated PO id={po_id}")
            return po
        except Exception as e:
            session.rollback()
            logger.exception("Error updating purchase order")
            raise

    @staticmethod
    def delete_po(session, po_id):
        po = session.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
        if not po:
            raise ValueError("Purchase order not found")
        try:
            session.delete(po)
            session.commit()
            logger.info(f"Deleted PO id={po_id}")
        except Exception as e:
            session.rollback()
            logger.exception("Error deleting purchase order")
            raise

    @staticmethod
    def list_pos(session):
        return (session.query(PurchaseOrder, Supplier.name.label("supplier_name"))
                .join(Supplier, PurchaseOrder.supplier_id == Supplier.id)
                .order_by(PurchaseOrder.order_date.desc())
                .all())

    @staticmethod
    def get_po_items(session, po_id):
        return session.query(POItem).filter(POItem.po_id == po_id).all()

    @staticmethod
    def get_dashboard_stats(session):
        total_pos = session.query(func.count(PurchaseOrder.id)).scalar() or 0
        suppliers = session.query(func.count(Supplier.id)).scalar() or 0
        pending = session.query(func.count(PurchaseOrder.id)).filter(PurchaseOrder.status == "Pending").scalar() or 0
        total_value = session.query(func.sum(PurchaseOrder.total)).scalar() or 0.0
        return {
            "total_pos": total_pos,
            "suppliers": suppliers,
            "pending": pending,
            "total_value": total_value,
        }


# --------------------------------------------------------------------------- #
#  UI Components
# --------------------------------------------------------------------------- #

# -------- Custom dialogs (styled) -------- #
def confirm(parent, title, message):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QMessageBox.Question)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    box.setStyleSheet("""
        QMessageBox { background-color: #1e2233; }
        QMessageBox QLabel { color: #e6e9f0; font-size: 13px; }
        QPushButton {
            background-color: #3a4163; color: #e6e9f0; border: none;
            padding: 6px 18px; border-radius: 6px; min-width: 70px;
        }
        QPushButton:hover { background-color: #4d5689; }
        QPushButton:default { background-color: #5b6bdf; }
    """)
    return box.exec_() == QMessageBox.Yes


def warn(parent, title, message):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QMessageBox.Warning)
    box.setStandardButtons(QMessageBox.Ok)
    box.setStyleSheet("""
        QMessageBox { background-color: #1e2233; }
        QMessageBox QLabel { color: #e6e9f0; font-size: 13px; }
        QPushButton {
            background-color: #3a4163; color: #e6e9f0; border: none;
            padding: 6px 18px; border-radius: 6px; min-width: 70px;
        }
        QPushButton:hover { background-color: #4d5689; }
    """)
    box.exec_()


def info(parent, title, message):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QMessageBox.Information)
    box.setStandardButtons(QMessageBox.Ok)
    box.setStyleSheet("""
        QMessageBox { background-color: #1e2233; }
        QMessageBox QLabel { color: #e6e9f0; font-size: 13px; }
        QPushButton {
            background-color: #3a4163; color: #e6e9f0; border: none;
            padding: 6px 18px; border-radius: 6px; min-width: 70px;
        }
        QPushButton:hover { background-color: #4d5689; }
    """)
    box.exec_()


# -------- Numeric table item for sorting -------- #
class NumericItem(QTableWidgetItem):
    def __lt__(self, other):
        try:
            return float(self.data(Qt.UserRole)) < float(other.data(Qt.UserRole))
        except (TypeError, ValueError):
            return super().__lt__(other)


# -------- Inline decimal delegate -------- #
class DecimalDelegate(QStyledItemDelegate):
    def __init__(self, decimals=2, parent=None):
        super().__init__(parent)
        self.decimals = decimals

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        validator = QDoubleValidator(0.0, 1_000_000_000.0, self.decimals, editor)
        validator.setNotation(QDoubleValidator.StandardNotation)
        editor.setValidator(validator)
        return editor


# -------- Editable item table -------- #
class ItemTable(QTableWidget):
    """Editable item table with Delete-key support and inline decimal editing."""

    totalChanged = pyqtSignal(float)

    def __init__(self):
        super().__init__(0, 4)
        self.setHorizontalHeaderLabels(["Description", "Qty", f"Unit Price ({RUPEE})", f"Amount ({RUPEE})"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            self.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setItemDelegateForColumn(1, DecimalDelegate(2, self))
        self.setItemDelegateForColumn(2, DecimalDelegate(2, self))
        self.itemChanged.connect(self._on_item_changed)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and not self.state() == QAbstractItemView.EditingState:
            self.remove_selected()
        else:
            super().keyPressEvent(event)

    def add_row(self, desc="", qty="1", price="0.00"):
        self.blockSignals(True)
        r = self.rowCount()
        self.insertRow(r)
        self.setItem(r, 0, QTableWidgetItem(desc))
        qty_item = QTableWidgetItem(str(qty))
        qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setItem(r, 1, qty_item)
        price_item = QTableWidgetItem(str(price))
        price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setItem(r, 2, price_item)
        amount = QTableWidgetItem("0.00")
        amount.setFlags(Qt.ItemIsEnabled)
        amount.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setItem(r, 3, amount)
        self.blockSignals(False)
        self._recalc_row(r)

    def remove_selected(self):
        rows = sorted({i.row() for i in self.selectedItems()}, reverse=True)
        for r in rows:
            self.removeRow(r)
        self._emit_total()

    def _on_item_changed(self, item):
        if item.column() in (1, 2):
            self._recalc_row(item.row())

    def _recalc_row(self, r):
        qty = self._num(r, 1)
        price = self._num(r, 2)
        amount = qty * price
        self.blockSignals(True)
        amt_item = self.item(r, 3)
        if amt_item is None:
            amt_item = QTableWidgetItem()
            amt_item.setFlags(Qt.ItemIsEnabled)
            amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.setItem(r, 3, amt_item)
        amt_item.setText(f"{amount:,.2f}")
        self.blockSignals(False)
        self._emit_total()

    def _num(self, r, c):
        item = self.item(r, c)
        if item is None:
            return 0.0
        try:
            return float(item.text().replace(",", ""))
        except ValueError:
            return 0.0

    def total(self):
        return sum(self._num(r, 1) * self._num(r, 2) for r in range(self.rowCount()))

    def _emit_total(self):
        self.totalChanged.emit(self.total())

    def get_items(self):
        """Return list of (description, quantity, unit_price) for non-empty rows."""
        result = []
        for r in range(self.rowCount()):
            desc_item = self.item(r, 0)
            desc = desc_item.text().strip() if desc_item else ""
            if not desc:
                continue
            result.append((desc, self._num(r, 1), self._num(r, 2)))
        return result

    def set_items(self, items):
        """Populate table from list of (description, quantity, unit_price)."""
        self.blockSignals(True)
        self.setRowCount(0)
        for desc, qty, price in items:
            self.add_row(desc, str(qty), str(price))
        self.blockSignals(False)
        self._emit_total()


# -------- Dashboard stat cards -------- #
class StatCard(QFrame):
    def __init__(self, title, accent):
        super().__init__()
        self.setObjectName("stat")
        self.setStyleSheet(f"#stat {{ border-left: 4px solid {accent}; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        self.value_lbl = QLabel("0")
        self.value_lbl.setObjectName("statValue")
        title_lbl = QLabel(title)
        title_lbl.setObjectName("statTitle")
        v.addWidget(self.value_lbl)
        v.addWidget(title_lbl)

    def set_value(self, text):
        self.value_lbl.setText(text)


class StatStrip(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 0)
        layout.setSpacing(12)
        self.total_pos = StatCard("Total Purchase Orders", "#5b6bdf")
        self.suppliers = StatCard("Suppliers", "#22b8a6")
        self.pending = StatCard("Pending Orders", "#e0a93b")
        self.value = StatCard(f"Total Value", "#d65db1")
        for card in (self.total_pos, self.suppliers, self.pending, self.value):
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            layout.addWidget(card)

    def set_stats(self, stats):
        self.total_pos.set_value(str(stats["total_pos"]))
        self.suppliers.set_value(str(stats["suppliers"]))
        self.pending.set_value(str(stats["pending"]))
        self.value.set_value(fmt_money(stats["total_value"]))


# -------- Supplier Tab -------- #
class SupplierTab(QWidget):
    def __init__(self, status_bar):
        super().__init__()
        self.status_bar = status_bar
        self.current_id = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Form panel
        form_frame = QFrame()
        form_frame.setObjectName("card")
        form_frame.setMaximumWidth(360)
        form = QFormLayout(form_frame)
        form.setSpacing(10)

        self.name_in = QLineEdit()
        self.gstin_in = QLineEdit()
        self.gstin_in.setPlaceholderText("22AAAAA0000A1Z5")
        self.gstin_in.setMaxLength(15)
        self.email_in = QLineEdit()
        self.email_in.setPlaceholderText("name@company.com")
        self.phone_in = QLineEdit()
        self.phone_in.setPlaceholderText("10-digit number")
        self.phone_in.setValidator(QRegExpValidator(QRegExp(r"\d{0,15}")))
        self.address_in = QTextEdit()
        self.address_in.setFixedHeight(70)

        form.addRow("Name *", self.name_in)
        form.addRow("GSTIN", self.gstin_in)
        form.addRow("Email", self.email_in)
        form.addRow("Phone", self.phone_in)
        form.addRow("Address", self.address_in)

        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save)
        self.new_btn = QPushButton("Clear")
        self.new_btn.setObjectName("secondary")
        self.new_btn.clicked.connect(self.clear_form)
        self.del_btn = QPushButton("Delete")
        self.del_btn.setObjectName("danger")
        self.del_btn.clicked.connect(self.delete)
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.new_btn)
        btn_row.addWidget(self.del_btn)
        form.addRow(btn_row)

        # Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "GSTIN", "Email", "Phone", "Address"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.cellClicked.connect(self.load_row)

        layout.addWidget(form_frame)
        layout.addWidget(self.table, 1)

    def clear_form(self):
        self.current_id = None
        self.name_in.clear()
        self.gstin_in.clear()
        self.email_in.clear()
        self.phone_in.clear()
        self.address_in.clear()
        self.table.clearSelection()

    def _validate(self):
        name = self.name_in.text().strip()
        gstin = self.gstin_in.text().strip().upper()
        email = self.email_in.text().strip()
        phone = self.phone_in.text().strip()
        if not name:
            warn(self, "Validation", "Supplier name is required.")
            return None
        if gstin and not validate_gstin(gstin):
            warn(self, "Validation", "GSTIN must be a valid 15-character GST number.")
            return None
        if email and not validate_email(email):
            warn(self, "Validation", "Email address is not in a valid format.")
            return None
        if phone and not validate_phone(phone):
            warn(self, "Validation", "Phone must contain only digits (7-15 long).")
            return None
        return name, gstin, email, phone, self.address_in.toPlainText().strip()

    def save(self):
        data = self._validate()
        if not data:
            return
        name, gstin, email, phone, address = data

        def db_operation(session):
            if self.current_id is None:
                supplier = SupplierService.add_supplier(session, name, gstin, email, phone, address)
                msg = f"Supplier '{supplier.name}' added."
            else:
                supplier = SupplierService.update_supplier(session, self.current_id, name, gstin, email, phone, address)
                msg = f"Supplier '{supplier.name}' updated."
            return msg

        self._run_db_task(db_operation, "Saving supplier...", on_success=self._on_save_success)

    def _on_save_success(self, msg):
        self.clear_form()
        self.refresh()
        self.status_bar.showMessage(msg, 3000)

    def delete(self):
        if self.current_id is None:
            warn(self, "Delete", "Select a supplier to delete.")
            return

        def db_operation(session):
            SupplierService.delete_supplier(session, self.current_id)
            return "Supplier deleted."

        self._run_db_task(db_operation, "Deleting supplier...", on_success=self._on_delete_success)

    def _on_delete_success(self, msg):
        self.clear_form()
        self.refresh()
        self.status_bar.showMessage(msg, 3000)

    def _run_db_task(self, func, progress_msg, on_success=None):
        """Run a database operation in background thread."""
        def do_in_thread():
            session = get_db_session()
            try:
                result = func(session)
                return result
            except Exception as e:
                logger.exception("DB operation failed")
                return e
            finally:
                session.close()

        worker = DbWorker(do_in_thread)
        worker.finished.connect(self._on_task_finished(on_success))
        worker.error.connect(lambda msg: warn(self, "Database Error", msg))
        self.status_bar.showMessage(progress_msg)
        worker.start()

    def _on_task_finished(self, callback):
        def inner(result):
            if isinstance(result, Exception):
                warn(self, "Error", str(result))
            elif callback:
                callback(result)
        return inner

    def load_row(self, row, _col):
        supplier_id = self.table.item(row, 0).data(Qt.UserRole)
        self.current_id = supplier_id
        # load from DB in background
        def db_operation(session):
            return SupplierService.get_supplier(session, supplier_id)

        def on_loaded(supplier):
            if supplier:
                self.name_in.setText(supplier.name or "")
                self.gstin_in.setText(supplier.gstin or "")
                self.email_in.setText(supplier.email or "")
                self.phone_in.setText(supplier.phone or "")
                self.address_in.setText(supplier.address or "")
        self._run_db_task(db_operation, "Loading supplier...", on_success=on_loaded)

    def refresh(self):
        def db_operation(session):
            return SupplierService.list_suppliers(session)

        def on_loaded(suppliers):
            self.table.setSortingEnabled(False)
            self.table.setRowCount(len(suppliers))
            for r, s in enumerate(suppliers):
                name_item = QTableWidgetItem(s.name or "")
                name_item.setData(Qt.UserRole, s.id)
                self.table.setItem(r, 0, name_item)
                self.table.setItem(r, 1, QTableWidgetItem(s.gstin or ""))
                self.table.setItem(r, 2, QTableWidgetItem(s.email or ""))
                self.table.setItem(r, 3, QTableWidgetItem(s.phone or ""))
                self.table.setItem(r, 4, QTableWidgetItem(s.address or ""))
            self.table.setSortingEnabled(True)
            self.status_bar.showMessage(f"Loaded {len(suppliers)} suppliers", 2000)

        self._run_db_task(db_operation, "Loading suppliers...", on_success=on_loaded)


# -------- Purchase Order Tab -------- #
class PurchaseOrderTab(QWidget):
    STATUSES = ["Pending", "Approved", "Received", "Cancelled"]

    def __init__(self, status_bar):
        super().__init__()
        self.status_bar = status_bar
        self.current_id = None
        self._workers = []                     # <-- FIXED: added this line
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # ---- Left: form ----
        form_frame = QFrame()
        form_frame.setObjectName("card")
        form_frame.setMaximumWidth(440)
        v = QVBoxLayout(form_frame)
        form = QFormLayout()
        form.setSpacing(10)

        self.po_in = QLineEdit()
        self.po_in.setPlaceholderText("PO-0001")
        self.supplier_cb = QComboBox()
        self.order_date = QDateEdit(QDate.currentDate())
        self.order_date.setCalendarPopup(True)
        self.order_date.setDisplayFormat("yyyy-MM-dd")
        self.due_date = QDateEdit(QDate.currentDate().addDays(7))
        self.due_date.setCalendarPopup(True)
        self.due_date.setDisplayFormat("yyyy-MM-dd")
        self.status_cb = QComboBox()
        self.status_cb.addItems(self.STATUSES)
        self.notes_in = QTextEdit()
        self.notes_in.setFixedHeight(60)

        form.addRow("PO Number *", self.po_in)
        form.addRow("Supplier *", self.supplier_cb)
        form.addRow("Order Date *", self.order_date)
        form.addRow("Due Date *", self.due_date)
        form.addRow("Status", self.status_cb)
        form.addRow("Notes", self.notes_in)
        v.addLayout(form)

        # Items section
        items_header = QHBoxLayout()
        items_label = QLabel("Items")
        items_label.setObjectName("sectionLabel")
        add_item_btn = QPushButton("+ Add Item")
        add_item_btn.setObjectName("secondary")
        add_item_btn.clicked.connect(lambda: self.items_table.add_row())
        del_item_btn = QPushButton("Remove")
        del_item_btn.setObjectName("secondary")
        del_item_btn.clicked.connect(lambda: self.items_table.remove_selected())
        items_header.addWidget(items_label)
        items_header.addStretch()
        items_header.addWidget(add_item_btn)
        items_header.addWidget(del_item_btn)
        v.addLayout(items_header)

        self.items_table = ItemTable()
        self.items_table.totalChanged.connect(self._update_total)
        self.items_table.setMinimumHeight(150)
        v.addWidget(self.items_table)

        hint = QLabel("Tip: select a row and press Delete to remove it.")
        hint.setObjectName("hint")
        v.addWidget(hint)

        self.total_label = QLabel(f"Total: {fmt_money(0)}")
        self.total_label.setObjectName("totalLabel")
        self.total_label.setAlignment(Qt.AlignRight)
        v.addWidget(self.total_label)

        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("Save PO")
        self.save_btn.clicked.connect(self.save)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("secondary")
        self.clear_btn.clicked.connect(self.clear_form)
        self.del_btn = QPushButton("Delete")
        self.del_btn.setObjectName("danger")
        self.del_btn.clicked.connect(self.delete)
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addWidget(self.del_btn)
        v.addLayout(btn_row)

        # ---- Right: list ----
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["PO Number", "Supplier", "Order Date", "Due Date", "Status", f"Total ({RUPEE})"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        self.table.cellClicked.connect(self.load_row)

        layout.addWidget(form_frame)
        layout.addWidget(self.table, 1)

        if self.items_table.rowCount() == 0:
            self.items_table.add_row()

    def reload_suppliers(self):
        def db_operation(session):
            return SupplierService.list_suppliers(session)

        def on_loaded(suppliers):
            current = self.supplier_cb.currentData()
            self.supplier_cb.clear()
            for s in suppliers:
                self.supplier_cb.addItem(s.name, s.id)
            if current is not None:
                idx = self.supplier_cb.findData(current)
                if idx >= 0:
                    self.supplier_cb.setCurrentIndex(idx)

        self._run_db_task(db_operation, "Loading suppliers...", on_success=on_loaded)

    def _update_total(self, total):
        self.total_label.setText(f"Total: {fmt_money(total)}")

    def clear_form(self):
        self.current_id = None
        self.po_in.clear()
        self.order_date.setDate(QDate.currentDate())
        self.due_date.setDate(QDate.currentDate().addDays(7))
        self.status_cb.setCurrentIndex(0)
        self.notes_in.clear()
        self.items_table.setRowCount(0)      # <-- FIXED: was set_row_count
        self.items_table.add_row()
        self.table.clearSelection()
        self._update_total(0.0)

    def _validate(self):
        po_number = self.po_in.text().strip()
        if not po_number:
            warn(self, "Validation", "PO Number is required.")
            return None
        if self.supplier_cb.currentData() is None:
            warn(self, "Validation", "Please add and select a supplier first.")
            return None
        # Duplicate check will be done in service with DB call; we'll catch it later.
        order_d = self.order_date.date()
        due_d = self.due_date.date()
        if due_d < order_d:
            warn(self, "Validation", "Due date must be on or after the order date.")
            return None
        items = self.items_table.get_items()
        if not items:
            warn(self, "Validation", "Add at least one item with a description.")
            return None
        return (po_number, self.supplier_cb.currentData(),
                parse_date(order_d), parse_date(due_d),
                self.status_cb.currentText(),
                self.notes_in.toPlainText().strip(), items)

    def save(self):
        data = self._validate()
        if not data:
            return
        po_number, sid, order_d, due_d, status, notes, items = data

        def db_operation(session):
            if self.current_id is None:
                po = PurchaseOrderService.add_po(session, po_number, sid, order_d, due_d, status, notes, items)
                msg = f"PO '{po.po_number}' created."
            else:
                po = PurchaseOrderService.update_po(session, self.current_id, po_number, sid, order_d, due_d, status, notes, items)
                msg = f"PO '{po.po_number}' updated."
            return msg

        self._run_db_task(db_operation, "Saving purchase order...", on_success=self._on_save_success)

    def _on_save_success(self, msg):
        self.clear_form()
        self.refresh()
        self.status_bar.showMessage(msg, 3000)

    def delete(self):
        if self.current_id is None:
            warn(self, "Delete", "Select a purchase order to delete.")
            return

        def db_operation(session):
            PurchaseOrderService.delete_po(session, self.current_id)
            return "Purchase order deleted."

        self._run_db_task(db_operation, "Deleting purchase order...", on_success=self._on_delete_success)

    def _on_delete_success(self, msg):
        self.clear_form()
        self.refresh()
        self.status_bar.showMessage(msg, 3000)

    def _run_db_task(self, func, progress_msg, on_success=None):
        def do_in_thread():
            session = get_db_session()
            try:
                result = func(session)
                return result
            except Exception as e:
                logger.exception("DB operation failed")
                return e
            finally:
                session.close()

        worker = DbWorker(do_in_thread)
        worker.finished.connect(self._on_task_finished(on_success))
        worker.error.connect(lambda msg: warn(self, "Database Error", msg))
        self._workers.append(worker)  # keep reference
        self.status_bar.showMessage(progress_msg)
        worker.start()

    def _on_task_finished(self, callback):
        def inner(result):
            if isinstance(result, Exception):
                warn(self, "Error", str(result))
            elif callback:
                callback(result)
        return inner

    def load_row(self, row, _col):
        po_id = self.table.item(row, 0).data(Qt.UserRole)
        self.current_id = po_id

        def db_operation(session):
            po = session.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
            items = PurchaseOrderService.get_po_items(session, po_id)
            return po, items

        def on_loaded(result):
            po, items = result
            if po:
                self.po_in.setText(po.po_number)
                idx = self.supplier_cb.findData(po.supplier_id)
                if idx >= 0:
                    self.supplier_cb.setCurrentIndex(idx)
                self.order_date.setDate(QDate.fromString(po.order_date.strftime("%Y-%m-%d"), "yyyy-MM-dd"))
                self.due_date.setDate(QDate.fromString(po.due_date.strftime("%Y-%m-%d"), "yyyy-MM-dd"))
                si = self.status_cb.findText(po.status)
                if si >= 0:
                    self.status_cb.setCurrentIndex(si)
                self.notes_in.setText(po.notes or "")
                # load items
                item_list = [(it.description, it.quantity, it.unit_price) for it in items]
                self.items_table.set_items(item_list)
                if self.items_table.rowCount() == 0:
                    self.items_table.add_row()
                self._update_total(po.total)

        self._run_db_task(db_operation, "Loading purchase order...", on_success=on_loaded)

    def refresh(self):
        self.reload_suppliers()

        def db_operation(session):
            return PurchaseOrderService.list_pos(session)

        def on_loaded(pos):
            self.table.setSortingEnabled(False)
            self.table.setRowCount(len(pos))
            for r, (po, supplier_name) in enumerate(pos):
                po_item = QTableWidgetItem(po.po_number)
                po_item.setData(Qt.UserRole, po.id)
                self.table.setItem(r, 0, po_item)
                self.table.setItem(r, 1, QTableWidgetItem(supplier_name))
                self.table.setItem(r, 2, QTableWidgetItem(po.order_date.strftime("%Y-%m-%d")))
                self.table.setItem(r, 3, QTableWidgetItem(po.due_date.strftime("%Y-%m-%d")))
                self.table.setItem(r, 4, QTableWidgetItem(po.status))
                total_item = NumericItem(fmt_money(po.total))
                total_item.setData(Qt.UserRole, po.total)
                total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, 5, total_item)
            self.table.setSortingEnabled(True)
            self.status_bar.showMessage(f"Loaded {len(pos)} purchase orders", 2000)

        self._run_db_task(db_operation, "Loading purchase orders...", on_success=on_loaded)


# -------- Main Window -------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(CONFIG["app"]["title"])
        self.resize(CONFIG["app"]["window_width"], CONFIG["app"]["window_height"])

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready", 2000)

        # Dashboard
        self.stat_strip = StatStrip()
        root.addWidget(self.stat_strip)

        # Tabs
        self.tabs = QTabWidget()
        self.po_tab = PurchaseOrderTab(self.status_bar)
        self.supplier_tab = SupplierTab(self.status_bar)
        self.tabs.addTab(self.po_tab, "Purchase Orders")
        self.tabs.addTab(self.supplier_tab, "Suppliers")
        root.addWidget(self.tabs, 1)

        self.setCentralWidget(central)

        # Initial refresh (async)
        self.refresh_all()

        # Timer to refresh dashboard periodically (e.g., every 60 seconds)
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_stats)
        self.timer.start(60000)

    def refresh_all(self):
        self.refresh_stats()
        self.po_tab.refresh()
        self.supplier_tab.refresh()

    def refresh_stats(self):
        def db_operation(session):
            return PurchaseOrderService.get_dashboard_stats(session)

        def on_stats(stats):
            self.stat_strip.set_stats(stats)

        # Use a worker to avoid blocking UI
        worker = DbWorker(db_operation)
        worker.finished.connect(on_stats)
        worker.error.connect(lambda msg: logger.error(f"Stats error: {msg}"))
        worker.start()
        # keep reference
        if not hasattr(self, '_stats_workers'):
            self._stats_workers = []
        self._stats_workers.append(worker)


# --------------------------------------------------------------------------- #
#  Application entry point
# --------------------------------------------------------------------------- #
def main():
    app = QApplication(sys.argv)

    # Set application style
    app.setStyleSheet("""
        QWidget {
            background-color: #161a27;
            color: #e6e9f0;
            font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
            font-size: 13px;
        }
        QTabWidget::pane { border: none; background: #161a27; }
        QTabBar::tab {
            background: #1e2233; color: #9aa3bd; padding: 10px 22px;
            border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 4px;
        }
        QTabBar::tab:selected { background: #5b6bdf; color: #ffffff; }
        QTabBar::tab:hover:!selected { background: #2a3048; color: #e6e9f0; }

        #card {
            background-color: #1e2233; border-radius: 12px; padding: 6px;
        }
        #stat {
            background-color: #1e2233; border-radius: 12px;
        }
        #statValue { font-size: 22px; font-weight: 700; color: #ffffff; }
        #statTitle { font-size: 11px; color: #9aa3bd; }
        #sectionLabel { font-size: 14px; font-weight: 600; }
        #totalLabel { font-size: 16px; font-weight: 700; color: #22b8a6; padding: 4px; }
        #hint { color: #6f7896; font-size: 11px; font-style: italic; }

        QLineEdit, QComboBox, QDateEdit, QTextEdit {
            background-color: #11141f; border: 1px solid #2a3048; border-radius: 6px;
            padding: 6px 8px; color: #e6e9f0; selection-background-color: #5b6bdf;
        }
        QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTextEdit:focus {
            border: 1px solid #5b6bdf;
        }
        QComboBox QAbstractItemView {
            background-color: #1e2233; selection-background-color: #5b6bdf;
            border: 1px solid #2a3048;
        }

        QPushButton {
            background-color: #5b6bdf; color: #ffffff; border: none;
            padding: 8px 16px; border-radius: 6px; font-weight: 600;
        }
        QPushButton:hover { background-color: #6d7cf0; }
        QPushButton:pressed { background-color: #4a59c4; }
        QPushButton#secondary { background-color: #3a4163; }
        QPushButton#secondary:hover { background-color: #4d5689; }
        QPushButton#danger { background-color: #c0455a; }
        QPushButton#danger:hover { background-color: #d6556b; }

        QTableWidget {
            background-color: #1e2233; alternate-background-color: #232840;
            gridline-color: #2a3048; border: none; border-radius: 8px;
        }
        QTableWidget::item { padding: 6px; }
        QTableWidget::item:selected { background-color: #5b6bdf; color: #ffffff; }
        QTableWidget::item:hover { background-color: #2f3656; }
        QHeaderView::section {
            background-color: #11141f; color: #9aa3bd; padding: 8px;
            border: none; border-bottom: 2px solid #5b6bdf; font-weight: 600;
        }
        QScrollBar:vertical { background: #161a27; width: 10px; margin: 0; }
        QScrollBar::handle:vertical { background: #3a4163; border-radius: 5px; min-height: 24px; }
        QScrollBar::handle:vertical:hover { background: #4d5689; }
        QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
    """)

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()