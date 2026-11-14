# Changing things in Parro

The client [reads](../README.md). It can change five things in Parro, and only when you ask for it.
This guide says how, who notices, and what can be undone.

## The rules for all of them

- **Nothing happens on its own.** Reading, showing or syncing something never changes it.
- **Each needs a command you run on purpose.** Apart from those calls, the Parro API only receives
  `GET`.
- **For an assistant, each is off unless you switch it on,** with a setting of its own. One switch
  does not open another.

Sending or deleting a message, signing up or withdrawing, and answering an invitation also follow
these rules:

- **You see it first.** The client shows what would happen and asks. Anything but `y` changes
  nothing.
- **`--yes` skips the question,** for scripts. Without a terminal and without `--yes`, nothing
  changes.
- **Never repeated on its own.** After a timeout or a server error, the client says it may or may
  not have gone through.
- **An assistant gets a preview first.** Called without `confirm: true`, the MCP tool changes nothing
  and returns the preview, so the assistant can show you what would happen.

## Marking as read

`overview` shows only what you have not read yet. Reading something here does not change that:
**nothing is ever marked as read on its own**, not by showing an announcement, opening a chat or
running `sync`. You mark items yourself:

```bash
parro-client mark-read announcement <id>      # also: calendar <id>, chat <chatroom-id>
parro-client announcement <id> --mark-read    # show it, then mark it
parro-client mark-read group <group-id>       # how many unread announcements a group has …
parro-client mark-read group <group-id> --yes # … and mark them all
```

**The school sees it.** Teachers see who read an announcement ("read by 31 of 45"), chats show read
receipts, and the Parro app on your phone shows the item as read too. So mark only what you have
actually read. The client first fetches the item, so a wrong id is an error, not a write; an item
that is already read is left alone.

The MCP tool `parro_mark_read` (one item at a time, no groups) is **off unless you switch it on**
with `PARRO_ALLOW_MARK_READ=1`, so an assistant cannot mark things while summarising them. MCP
clients see it marked as not read-only, so they ask before calling it.

## Sending a chat message

`chat-send` sends a text message to a chat you are already in:

```bash
parro-client chat-send <chatroom-id> "Ik kan rijden op de 12e"
parro-client chat-send <chatroom-id> --file bericht.txt   # or --file - for standard input
```

It first shows the chat, **who will receive the message** and the exact text, and asks
`Send this message? [y/N]`.

**Real people receive it, under your name:** the teacher, or everyone in a group chat. As far as we
know a message cannot be taken back, so treat sending as final.

- It refuses empty text and chats that are archived, that you have left, that have replies switched
  off, or that are with a bot.
- After a timeout or a server error, the message may or may not have arrived. Look at
  `chat-messages <chatroom-id>` before you try again.
- The text is never logged or stored, and sending does not mark the chat as read.
- Only text, only existing chats: no new chats, replies to one message, attachments or editing.
  A message of your own can be [deleted](#deleting-a-chat-message).

**From an assistant.** The MCP tool is `parro_send_chat_message`, switched on with
`PARRO_ALLOW_SEND_CHAT=1`. Its preview shows who would receive what.

> **Think before you switch this on.** An assistant also reads what other people write in Parro.
> Text in a chat or a newsletter could try to talk it into sending a message, and whatever it can
> read (your children's names, school letters) could end up in that message. The tool is marked as
> destructive, so MCP clients that honour this ask you before each call. **Leave that approval on
> for this tool**, and read the preview before you agree.

## Deleting a chat message

You can delete a message **you wrote yourself**. `chat-messages` shows the id on your own messages:

```bash
parro-client chat-messages <chatroom-id>             # your messages show #<message-id>
parro-client chat-delete <chatroom-id> <message-id>  # shows the message and asks
```

**It cannot be undone, and others see it.** The message stays in the chat as "(message deleted)",
for everyone. People who already read it, have read it.

- It refuses a message someone else wrote, a message that is already deleted, and lines such as
  "joined the chat". Whose message it is, is read from Parro again just before, not taken from
  what was shown earlier.
- After a timeout or a server error, the message may or may not have been deleted. Look at
  `chat-messages <chatroom-id>` before you try again.
- In the desktop app, your own messages have a small *Delete*; it shows the message, and only
  **Confirm** deletes it.

**From an assistant.** The MCP tool is `parro_delete_chat_message`, switched on with
`PARRO_ALLOW_DELETE_CHAT=1`. Without `confirm: true` it only shows which message it would delete.
The warning under [sending](#sending-a-chat-message) applies here too: text in Parro could try to
talk an assistant into deleting something, so leave your MCP client's approval on for this tool.

## Helping out

Some calendar items ask parents to help (driving, reading aloud) or to bring something.
`calendar --details` shows each slot with its id, how many signed up and whether you did. `helper`
signs you up or withdraws you, with the event id you already see:

```bash
parro-client helper signup <event-id>            # one place
parro-client helper signup <event-id> --count 3  # for example three children in your car
parro-client helper withdraw <event-id>
```

If an item has several slots, add `--slot <slot-id>`; without it the client lists them. It first
shows the item, its date, the slot, how many places are taken and your count, and asks
`Sign up for this slot? [y/N]` (or `Withdraw from this slot? [y/N]`).

**A sign-up is a promise.** The school sees your name on the slot, other parents at least see the
count go up, and you may take the last place. Withdrawing frees your place, and nobody may notice in
time. Whether teachers get a notification is not known.

- It refuses an item that asks for no helpers, an item in the past, a full slot, a count that does
  not fit the places left, signing up where you already have, and withdrawing where you have not.
- To change your count: withdraw and sign up again.
- Running the command again after a timeout or a server error is safe, because it first reads
  whether you are signed up.
- Only helper slots, only for yourself: no parent–teacher talk times, no signing up someone else.
  To answer an invitation, see [below](#answering-an-invitation).

**From an assistant.** The MCP tools are `parro_helper_signup` and `parro_helper_withdraw`, switched
on with `PARRO_ALLOW_HELPER_SIGNUP=1`.

> **Think before you switch this on.** An assistant also reads what other people write in Parro, and
> a newsletter that says "sign up for this" could try to talk it into making a promise in your
> name. These tools send no free text, and a sign-up can be undone, but only if you notice it. MCP
> clients that honour the hints ask before a withdrawal; **also keep approval on for the sign-up**,
> which is not marked as destructive, and read the preview before you agree.

## Answering an invitation

Some calendar items ask for an answer; the agenda marks them *RSVP needed*, and shows your answer
once you gave one. `rsvp` answers with the event id you already see:

```bash
parro-client rsvp accept <event-id>
parro-client rsvp decline <event-id>
parro-client rsvp tentative <event-id>
```

It first shows the item, its date and group, your current answer and the new one, and asks
`Accept this invitation? [y/N]`.

**The school sees your answer, under your name,** and it may decide what gets arranged. The Parro app
does not show parents who answered what, but the API does return it to a parent's login, so don't
treat your answer as hidden from other parents. Whether teachers get a notification is not known.

- **You can change an answer, not remove it.** A new answer replaces the old one, and the client
  shows both before asking. There is no way back to "not answered".
- It refuses an item that does not ask for an answer, an item that is cancelled and an item in the
  past.
- The answer you already gave is not sent again.
- Running the command again after a timeout or a server error is safe, because it first reads your
  current answer.
- Only for yourself and one item at a time, and without a note. Parent–teacher talk times are
  something else, and not covered.

**Other people's answers.** The API also returns everyone an invitation went to, with their names,
their children's names and their answers. The client has no command for that list, and the MCP tools
`parro_get` and `parro_attachment` refuse it, so an assistant cannot read it. Only the command
`get` can, if you ask for that path yourself. Please be careful with what it shows.

**From an assistant.** The MCP tool is `parro_rsvp`, switched on with `PARRO_ALLOW_RSVP=1`.

> **Think before you switch this on.** An assistant also reads what other people write in Parro, and
> a newsletter that says "please accept this" could try to talk it into answering in your name. The
> tool sends no free text, but a wrong answer can only be replaced, not removed. It is marked as
> destructive, so MCP clients that honour this ask you before each call. **Leave that approval on**,
> and read the preview before you agree.
