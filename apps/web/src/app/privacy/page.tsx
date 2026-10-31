import { CONTACT, LegalPage } from "@/components/legal";

export const metadata = { title: "Privacy policy · Agentry" };

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy policy" updated="31 October 2026">
      <p>
        Agentry builds and runs AI agents for businesses: they answer messages, calls and email, follow up leads, send reminders and keep
        records on the business&apos;s behalf. This policy explains what information we handle, why, and the choices you have.
      </p>

      <h2>Who is responsible</h2>
      <p>
        For our own website and our customers&apos; accounts, Agentry is responsible. When a business uses Agentry to talk to its own customers
        (for example on WhatsApp), that business decides how its customers&apos; information is used and Agentry processes it on the
        business&apos;s instructions. Questions: <a href={`mailto:${CONTACT}`}>{CONTACT}</a>.
      </p>

      <h2>What we collect</h2>
      <ul>
        <li><strong>Account details</strong> of people who use the Agentry portal: name, email address, role and sign-in records.</li>
        <li>
          <strong>Messages and records</strong> that our customers connect to Agentry: WhatsApp, Telegram, website chat and email messages,
          call recordings and transcripts, appointments, invoices, receipts and contact details (name, phone number, email) of the people
          they talk to.
        </li>
        <li><strong>Website visitors:</strong> what you type into our chat or demo form, and basic technical logs (IP address, browser).</li>
      </ul>

      <h2>How we use it</h2>
      <ul>
        <li>To run the agents a business has switched on: reading and answering messages, booking appointments, sending reminders and alerts.</li>
        <li>To keep accounts secure, keep an audit log of who did what, and fix problems.</li>
        <li>To bill our customers for the service.</li>
      </ul>
      <p>We do not sell personal information and we do not use it for advertising.</p>

      <h2>Who we share it with</h2>
      <p>Only with the services needed to run Agentry, under their own data-protection terms:</p>
      <ul>
        <li>Meta (WhatsApp Business Platform) and Telegram, to send and receive messages a business has connected.</li>
        <li>Google and Microsoft, when a business connects its Gmail or Outlook mailbox.</li>
        <li>AI model providers (Google Gemini, OpenAI) to understand and write messages; they do not use this data to train their models under our API terms.</li>
        <li>LiveKit for phone calls, Razorpay and Stripe for payments, and Oracle Cloud, where our servers are hosted.</li>
      </ul>

      <h2>How long we keep it</h2>
      <p>
        While the business&apos;s account is active, and as each business sets it: for example, email text and call recordings are deleted
        after the retention period the business chooses. When an account closes, its data is deleted within 90 days, except records we must
        keep by law (such as invoices).
      </p>

      <h2 id="deletion">Your choices and data deletion</h2>
      <ul>
        <li>Reply <strong>STOP</strong> to any WhatsApp or Telegram message from an Agentry agent to stop further messages.</li>
        <li>
          To see, correct or delete your information, email <a href={`mailto:${CONTACT}`}>{CONTACT}</a> with the phone number or email
          address you used. We confirm and complete deletion within 30 days, or pass the request to the business you dealt with if it controls the data.
        </li>
      </ul>

      <h2>Security</h2>
      <p>
        Data is encrypted in transit (HTTPS) and connection tokens are encrypted at rest. Each business&apos;s data is kept separate at the
        database level, and access is limited by role and recorded in an audit log.
      </p>

      <h2>Changes</h2>
      <p>We will update this page when our practices change, with a new date at the top.</p>
    </LegalPage>
  );
}
