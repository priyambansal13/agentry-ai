import { CONTACT, LegalPage } from "@/components/legal";

export const metadata = { title: "Terms of service · Agentry" };

export default function TermsPage() {
  return (
    <LegalPage title="Terms of service" updated="31 October 2026">
      <p>These terms cover the use of Agentry&apos;s website and portal. A signed proposal or agreement with a business takes precedence over them.</p>

      <h2>The service</h2>
      <p>
        Agentry sets up and runs AI agents for a business. Agents start in approval mode, where a person approves what is sent; the business
        decides when an agent may act on its own and within which limits.
      </p>

      <h2>Your responsibilities</h2>
      <ul>
        <li>Only connect accounts (WhatsApp, email, payment gateways) you are allowed to use, and keep sign-in details private.</li>
        <li>Have the consent your customers&apos; country requires before messaging them, and honour opt-outs (Agentry stops messaging anyone who replies STOP).</li>
        <li>Follow the rules of the platforms you connect, including WhatsApp&apos;s Business and Commerce policies.</li>
        <li>Check important information before relying on it: AI can make mistakes, and Agentry flags what it is unsure about for a person.</li>
      </ul>

      <h2>Fees</h2>
      <p>Fees are as agreed in your proposal or plan. Monthly statements can be disputed within 7 days of being issued.</p>

      <h2>Data</h2>
      <p>
        Your business&apos;s data stays yours. We handle it as described in our <a href="/privacy">privacy policy</a>, and you can export it
        from the portal at any time.
      </p>

      <h2>Availability and liability</h2>
      <p>
        We work to keep Agentry available and correct, but the service is provided as is. To the extent the law allows, our liability is
        limited to the fees paid in the three months before the claim.
      </p>

      <h2>Ending the service</h2>
      <p>Either side can end the service with 30 days&apos; notice, unless your agreement says otherwise. You can export your data before it ends.</p>

      <h2>Contact</h2>
      <p><a href={`mailto:${CONTACT}`}>{CONTACT}</a></p>
    </LegalPage>
  );
}
