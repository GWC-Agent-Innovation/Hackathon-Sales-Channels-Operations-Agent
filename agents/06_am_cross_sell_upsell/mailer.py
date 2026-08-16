import asyncio

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType

from . import config

RECIPIENT_EMAIL = "naveenrajanm237@gmail.com"

OPPORTUNITY_EMAIL_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{subject}</title>
</head>
<body style="margin:0; padding:0; background-color:#f4f5f7; font-family:Arial, Helvetica, sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f5f7; padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:8px; overflow:hidden; border:1px solid #e5e7eb;">

          <tr>
            <td style="padding:32px 32px 8px 32px;">
              <p style="margin:0 0 16px 0; font-size:15px; line-height:1.6; color:#111827;">
                Hi {greeting_name} —
              </p>
              <p style="margin:0 0 16px 0; font-size:15px; line-height:1.6; color:#111827;">
                {intro_html}
              </p>
              <p style="margin:0 0 24px 0; font-size:15px; line-height:1.6; color:#111827;">
                {ask_html}
              </p>
              <p style="margin:0 0 4px 0; font-size:15px; line-height:1.6; color:#111827;">
                Best,
              </p>
              <p style="margin:0 0 24px 0; font-size:15px; line-height:1.6; color:#111827;">
                Naveen Rajan M
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 32px 32px 32px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb; border:1px solid #e5e7eb; border-radius:6px;">
                <tr>
                  <td style="padding:16px 20px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="font-size:11px; letter-spacing:0.05em; color:#6b7280; text-transform:uppercase; padding-bottom:4px;">
                          Opportunity Value
                        </td>
                        <td style="font-size:11px; letter-spacing:0.05em; color:#6b7280; text-transform:uppercase; padding-bottom:4px;">
                          Product
                        </td>
                      </tr>
                      <tr>
                        <td style="font-size:16px; font-weight:bold; color:#111827;">
                          {opportunity_value}
                        </td>
                        <td style="font-size:16px; font-weight:bold; color:#111827;">
                          {product}
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:16px 32px 32px 32px; border-top:1px solid #e5e7eb;">
              <p style="margin:0; font-size:12px; color:#9ca3af;">
                Sent regarding account: {account_name} · Opportunity ID: {opportunity_id}
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


class MailNotConfigured(RuntimeError):
    pass


def _connection_config() -> ConnectionConfig:
    if not config.MAIL_USERNAME or not config.MAIL_PASSWORD or not config.MAIL_FROM:
        raise MailNotConfigured(
            "MAIL_USERNAME / MAIL_PASSWORD / MAIL_FROM are not set in the shared .env - "
            "set them to your Fastmail SMTP credentials to enable outreach emails."
        )
    return ConnectionConfig(
        MAIL_USERNAME=config.MAIL_USERNAME,
        MAIL_PASSWORD=config.MAIL_PASSWORD,
        MAIL_FROM=config.MAIL_FROM,
        MAIL_FROM_NAME=config.MAIL_FROM_NAME,
        MAIL_PORT=config.MAIL_PORT,
        MAIL_SERVER=config.MAIL_SERVER,
        MAIL_STARTTLS=config.MAIL_STARTTLS,
        MAIL_SSL_TLS=config.MAIL_SSL_TLS,
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True,
    )


def render_opportunity_email(
    *,
    subject: str = "Scaling Northstar's security coverage for your recent growth",
    greeting_name: str = "Priya",
    intro_html: str = (
        "Congrats on the acquisition. Given the headcount increase, your current "
        "Endpoint Security licenses won't cover the expanded team."
    ),
    ask_html: str = "Want 15 minutes this week to size the upgrade?",
    sender_name: str = "Divya P.",
    opportunity_value: str = "$32,000",
    product: str = "Endpoint Security (expanded coverage)",
    account_name: str = "Northstar Managed Services",
    opportunity_id: str = "UP-501",
) -> str:
    return OPPORTUNITY_EMAIL_TEMPLATE.format(
        subject=subject,
        greeting_name=greeting_name,
        intro_html=intro_html,
        ask_html=ask_html,
        sender_name=sender_name,
        opportunity_value=opportunity_value,
        product=product,
        account_name=account_name,
        opportunity_id=opportunity_id,
    )


async def send_opportunity_email(
    subject: str = "Scaling Northstar's security coverage for your recent growth",
    to_email: str = RECIPIENT_EMAIL,
    **template_kwargs,
) -> None:
    message = MessageSchema(
        subject=subject,
        recipients=[to_email],
        body=render_opportunity_email(subject=subject, **template_kwargs),
        subtype=MessageType.html,
    )
    fm = FastMail(_connection_config())
    await fm.send_message(message)


def send_opportunity_email_sync(*args, **kwargs) -> None:
    asyncio.run(send_opportunity_email(*args, **kwargs))
