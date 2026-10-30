"""Writes sample-podcast.json: a 45-minute episode of "The Clinic Growth Show" with Dr. Neha Sharma, owner of
SmileCraft Dental (the demo client). Timestamped segments with speakers, like a transcriber's output. Deterministic."""
import json
from pathlib import Path

HOST, GUEST = "Host", "Dr. Neha Sharma"
LINES = [
    (HOST, "Welcome back to The Clinic Growth Show. Today I'm with Dr. Neha Sharma, who runs SmileCraft Dental in Pune. Neha, thanks for coming on."),
    (GUEST, "Thanks for having me. I've listened to this show for two years, so this is a bit surreal."),
    (HOST, "Let's start at the beginning. How did SmileCraft start?"),
    (GUEST, "I opened with one chair and one assistant in 2016. I had savings for exactly six months of rent, so the first year was pure survival."),
    (HOST, "What was the hardest part of that first year?"),
    (GUEST, "Not the dentistry. The dentistry I knew. The hard part was that the phone kept ringing while my hands were inside someone's mouth."),
    (GUEST, "We counted once. In one month we missed 140 calls. If even a third of those were new patients, that's more than forty people who called a competitor instead."),
    (HOST, "That's a big number. What did you do about it?"),
    (GUEST, "At first, nothing clever. I asked my assistant to call everyone back at lunch. But by lunch, most of them had already booked somewhere else."),
    (GUEST, "A missed call is not a missed call. It's a patient who chose someone else because we didn't pick up."),
    (HOST, "So speed matters more than we think."),
    (GUEST, "Speed is everything. People call three clinics and book with whoever answers first. Nobody compares your degrees at that moment."),
    (HOST, "Let's talk about no-shows. Every clinic owner I talk to complains about them."),
    (GUEST, "We had a no-show rate of almost 22 percent in 2019. That's one in five chairs empty for an hour, every single day."),
    (GUEST, "We started sending a WhatsApp reminder the evening before, with a simple question: reply 1 to confirm, 2 to reschedule. Within three months no-shows dropped to 8 percent."),
    (HOST, "Why do you think that worked so well?"),
    (GUEST, "Because rescheduling became easy. Most no-shows aren't rude people. They're people who felt awkward calling to cancel."),
    (GUEST, "If you make cancelling easy, people cancel instead of disappearing. And a cancellation you know about is a slot you can fill."),
    (HOST, "That's a nice way to put it. What about pricing? Dentistry has a reputation for surprise bills."),
    (GUEST, "Every patient at SmileCraft gets a written treatment plan with prices before we start. No exceptions, even for a simple filling."),
    (GUEST, "When we started doing that, our treatment acceptance went up, not down. People say yes when they aren't afraid of the bill."),
    (HOST, "Interesting. Most people assume showing prices scares patients away."),
    (GUEST, "Uncertainty scares patients away. A clear number, even a big one, lets them plan."),
    (HOST, "Let's talk about children. Kids' dentistry is its own world."),
    (GUEST, "With children, the first visit is not about teeth. It's about trust. We don't do any treatment on the first visit unless it's an emergency."),
    (GUEST, "We let them sit in the chair, press the buttons, look at the mirror. A child who leaves smiling comes back without a fight."),
    (HOST, "And the parents?"),
    (GUEST, "Parents are watching how you treat their child more than how you treat the tooth. That's your real marketing."),
    (HOST, "How do you think about reviews? Google reviews seem to decide everything now."),
    (GUEST, "We have about 380 Google reviews and I've read every one of them. The bad ones taught me more than the good ones."),
    (GUEST, "Almost every bad review was about waiting, not about the treatment. So we fixed the waiting."),
    (HOST, "How?"),
    (GUEST, "We stopped double-booking to cover no-shows, because the reminders fixed the no-shows. And we text patients if we're running more than fifteen minutes late."),
    (GUEST, "A patient who knows you're running late is patient. A patient who doesn't know is angry. Same delay, different review."),
    (HOST, "Let's talk about your team. How many people now?"),
    (GUEST, "Eleven people and four chairs. The front desk is the hardest role to hire for, by far."),
    (GUEST, "Your front desk person is the first and last face of your clinic. I'd rather hire for warmth and train the software than the other way round."),
    (HOST, "What does a great front desk person do differently?"),
    (GUEST, "They remember names. They notice when someone is nervous. And they never say 'we're fully booked' without offering the next slot."),
    (HOST, "You mentioned software. How much technology do you use?"),
    (GUEST, "We were one of the first clinics in Kothrud to use an intraoral scanner. Patients see their own teeth on a screen, and suddenly they understand why they need the treatment."),
    (GUEST, "Showing beats telling. When a patient sees the crack on the screen, I don't have to convince anyone."),
    (HOST, "What about AI? Everyone's talking about it."),
    (GUEST, "We use an AI assistant now for calls after hours and for WhatsApp questions. It answers the boring questions, like timings and parking, and books appointments into our calendar."),
    (GUEST, "Last month it booked 31 appointments outside clinic hours. Those are people who would have called someone else in the morning."),
    (HOST, "Were you worried patients would hate talking to a bot?"),
    (GUEST, "I was. But it tells them it's an assistant, and it hands over to my team the moment someone is in pain or upset. People don't mind a bot. They mind being ignored."),
    (HOST, "Let's talk about marketing. What has worked for you?"),
    (GUEST, "Honestly, community dental camps. We do one school camp every month, free check-ups. It's the best marketing we've ever done."),
    (GUEST, "We've screened over 3,000 children in those camps. Many of their parents are our patients now."),
    (GUEST, "Paid ads brought us clicks. Camps brought us families. Families stay for twenty years."),
    (HOST, "What about Sunday openings? I hear you're open on Sundays."),
    (GUEST, "We open on Sunday mornings. It's now our busiest half-day of the week, because that's when working parents can actually come."),
    (HOST, "Doesn't that burn out your team?"),
    (GUEST, "We rotate. Nobody works more than two Sundays a month, and Sunday shifts get a day off in the week. Burned-out staff give burned-out care."),
    (HOST, "Let's talk about mistakes. What would you do differently if you started today?"),
    (GUEST, "I would track numbers from day one. For three years I ran the clinic on feelings. I thought we were busy. We were busy, but not profitable."),
    (GUEST, "The day I looked at revenue per chair hour, everything changed. Some treatments I loved were actually losing us money."),
    (HOST, "That's brave to admit."),
    (GUEST, "Every clinic owner I know has a treatment they're proud of that quietly loses money. Measure it before you promote it."),
    (HOST, "One last question. What advice would you give a dentist opening their first clinic next year?"),
    (GUEST, "Answer every call, keep your promises on price, and be kind to nervous patients. Everything else, you can learn on the way."),
    (HOST, "Dr. Neha Sharma, thank you so much."),
    (GUEST, "Thank you. This was fun."),
]
DURATION = 45 * 60
seg_len = DURATION / len(LINES)
segments = []
for i, (speaker, text) in enumerate(LINES):
    start = round(i * seg_len, 1)
    segments.append({"start": start, "end": round(start + seg_len - 0.5, 1), "speaker": speaker, "text": text})
out = {"title": "The Clinic Growth Show: Dr. Neha Sharma on missed calls, no-shows and honest pricing",
       "duration_seconds": DURATION, "language": "en", "segments": segments}
Path(__file__).with_name("sample-podcast.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
print(len(segments), "segments,", DURATION // 60, "minutes")
