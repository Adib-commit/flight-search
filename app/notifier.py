"""Email notifications for price alerts via SMTP."""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .config import Settings


def send_price_alert(
    settings: Settings,
    *,
    to_email: str,
    origin: str,
    destination: str,
    departure: str,
    ret: str | None,
    new_price: float,
    old_price: float,
    currency: str,
    booking_url: str,
    carriers: list[str],
) -> None:
    """Send an HTML + plain-text price-drop email.

    Silently skips if SMTP_HOST is not configured.
    """
    if not settings.smtp_host:
        return

    subject = (
        f"✈ Price drop! {origin}→{destination} now {currency} {new_price:.2f}"
        f" (was {old_price:.2f})"
    )

    dates = f"{departure}" + (f" – {ret}" if ret else " (one-way)")
    book_section = (
        f'<p><a href="{booking_url}" style="background:#0ea5e9;color:#fff;'
        f'padding:8px 18px;border-radius:6px;text-decoration:none;font-weight:bold;">'
        f'🔗 Book now on Kiwi.com</a></p>'
        if booking_url
        else ""
    )

    html = f"""
<html><body style="font-family:sans-serif;color:#1e293b">
  <h2>✈ Flight Price Alert</h2>
  <p><b>Route:</b> {origin} → {destination} &nbsp;|&nbsp; <b>Dates:</b> {dates}</p>
  <p><b>Airlines:</b> {', '.join(carriers)}</p>
  <table style="border-collapse:collapse">
    <tr>
      <td style="padding:6px 12px;background:#f1f5f9">Previous best price</td>
      <td style="padding:6px 12px"><s>{currency} {old_price:.2f}</s></td>
    </tr>
    <tr>
      <td style="padding:6px 12px;background:#dcfce7;font-weight:bold">New best price</td>
      <td style="padding:6px 12px;color:#16a34a;font-weight:bold;font-size:1.2em">
        {currency} {new_price:.2f}
      </td>
    </tr>
  </table>
  {book_section}
  <p style="color:#64748b;font-size:.85em">
    This alert was triggered by the Flight Optimization price watcher.
  </p>
</body></html>"""

    plain = (
        f"Price drop: {origin}→{destination} ({dates})\n"
        f"Airlines: {', '.join(carriers)}\n"
        f"Was: {currency} {old_price:.2f}  →  Now: {currency} {new_price:.2f}\n"
        + (f"Book: {booking_url}\n" if booking_url else "")
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_tls:
            server.starttls()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from, [to_email], msg.as_string())


def send_watch_confirmation(
    settings: Settings,
    *,
    to_email: str,
    origin: str,
    destination: str,
    departure: str,
    ret: str | None,
    current_price: float | None,
    currency: str,
    booking_url: str,
    carriers: list[str],
) -> None:
    """Send a confirmation email when a new price watch is activated.

    Includes the current best price found at activation time.
    Silently skips if SMTP_HOST is not configured.
    """
    if not settings.smtp_host:
        return

    dates = f"{departure}" + (f" – {ret}" if ret else " (one-way)")
    subject = f"\u2705 Price watch activated: {origin}→{destination} ({departure})"

    if current_price is not None:
        price_row = f"""
  <tr>
    <td style="padding:6px 12px;background:#f1f5f9">Current best price</td>
    <td style="padding:6px 12px;color:#0ea5e9;font-weight:bold;font-size:1.15em">
      {currency} {current_price:.2f}
    </td>
  </tr>
  <tr>
    <td style="padding:6px 12px;background:#f1f5f9">Airlines</td>
    <td style="padding:6px 12px">{', '.join(carriers) or 'Various'}</td>
  </tr>"""
        price_plain = f"Current best price: {currency} {current_price:.2f}\nAirlines: {', '.join(carriers) or 'Various'}\n"
    else:
        price_row = "<tr><td colspan='2' style='padding:6px 12px;color:#64748b'>No price data available yet.</td></tr>"
        price_plain = "No price data available yet.\n"

    book_section = (
        f'<p><a href="{booking_url}" style="background:#0ea5e9;color:#fff;'
        f'padding:8px 18px;border-radius:6px;text-decoration:none;font-weight:bold;">'
        f'\U0001f517 View current best deal</a></p>'
        if booking_url
        else ""
    )

    html = f"""
<html><body style="font-family:sans-serif;color:#1e293b">
  <h2>\u2705 Price Watch Activated</h2>
  <p>Your price watch for <b>{origin} → {destination}</b> is now active.<br/>
  We’ll email you as soon as we find a lower price.</p>
  <table style="border-collapse:collapse">
    <tr>
      <td style="padding:6px 12px;background:#f1f5f9">Route</td>
      <td style="padding:6px 12px">{origin} → {destination}</td>
    </tr>
    <tr>
      <td style="padding:6px 12px;background:#f1f5f9">Dates</td>
      <td style="padding:6px 12px">{dates}</td>
    </tr>
    {price_row}
  </table>
  {book_section}
  <p style="color:#64748b;font-size:.85em">
    Checks run every hour automatically. You can also trigger an immediate check
    from the Flight Optimization app.
  </p>
</body></html>"""

    plain = (
        f"Price watch activated: {origin}→{destination} ({dates})\n"
        + price_plain
        + (f"View deal: {booking_url}\n" if booking_url else "")
        + "Checks run every hour. You will be emailed when a lower price is found.\n"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_tls:
            server.starttls()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from, [to_email], msg.as_string())

def send_admin_error_alert(
    settings: Settings,
    *,
    to_emails: list[str],
    level: str,
    logger_name: str,
    message: str,
    detail: str,
    when: str,
) -> None:
    """Email admins when an ERROR/CRITICAL is logged. Skips if SMTP unset or no recipients."""
    if not settings.smtp_host or not to_emails:
        return

    subject = f"\U0001f6a8 [{level}] Flight app error in {logger_name}"
    safe_detail = (detail or "").replace("<", "&lt;").replace(">", "&gt;")
    html = f"""
<html><body style="font-family:sans-serif;color:#1e293b">
  <h2 style="color:#dc2626">\U0001f6a8 Application error: {level}</h2>
  <table style="border-collapse:collapse">
    <tr><td style="padding:6px 12px;background:#f1f5f9">When</td><td style="padding:6px 12px">{when}</td></tr>
    <tr><td style="padding:6px 12px;background:#f1f5f9">Logger</td><td style="padding:6px 12px">{logger_name}</td></tr>
    <tr><td style="padding:6px 12px;background:#fee2e2">Message</td><td style="padding:6px 12px;font-weight:bold">{message}</td></tr>
  </table>
  <pre style="background:#0f172a;color:#e2e8f0;padding:12px;border-radius:6px;overflow:auto;font-size:.85em">{safe_detail}</pre>
  <p style="color:#64748b;font-size:.85em">Automated alert from the Flight Optimization error monitor.</p>
</body></html>"""
    plain = (
        f"[{level}] {logger_name}\nWhen: {when}\nMessage: {message}\n\n{detail}\n"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(to_emails)
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_tls:
            server.starttls()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from, to_emails, msg.as_string())


def send_password_reset_email(
    settings,
    *,
    to_email: str,
    reset_url: str,
    username: str,
) -> None:
    """Send a password-reset link email. Silently skips if SMTP_HOST is not configured."""
    if not settings.smtp_host:
        return

    subject = "✈ Flight Optimization — Password Reset"
    html = f"""
<html><body style="font-family:sans-serif;color:#1e293b">
  <h2>🔐 Reset your password</h2>
  <p>Hi <b>{username}</b>,</p>
  <p>We received a request to reset the password for your Flight Optimization account.</p>
  <p style="margin:1.5rem 0">
    <a href="{reset_url}" style="background:#0ea5e9;color:#fff;padding:10px 22px;
       border-radius:6px;text-decoration:none;font-weight:bold">
      🔒 Reset my password
    </a>
  </p>
  <p style="color:#64748b;font-size:.85em">This link expires in 30 minutes.<br>
  If you didn't request a reset, you can safely ignore this email.</p>
</body></html>"""
    plain = (
        f"Hi {username},\n\n"
        f"Reset your Flight Optimization password here:\n{reset_url}\n\n"
        f"This link expires in 30 minutes."
    )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_tls:
            server.starttls()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from, [to_email], msg.as_string())
