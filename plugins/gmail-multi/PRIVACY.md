# Privacy and your data — gmail-multi

gmail-multi gives Claude access to the Gmail accounts you register. This page says what it reads,
where that goes, and how long it stays.

## What it reads

Mail in the accounts you register, and only those: it connects over TLS to `imap.gmail.com`. A search
or read must name the account it is for.

## What it sends, and where

Mail, only when you approve each message, through `smtp.gmail.com`. Every send, reply and forward asks
you first, so an unattended run can never send. It connects to no server other than Google's own mail
servers.

## Where it keeps it

It keeps no copy of your mail. It stores:
- the list of your account addresses, in `~/.claude/gmail-multi/accounts.json`;
- each account's app password, in your OS credential store (Keychain, PasswordVault or
  secret-service), where **you** put it. The plugin never accepts, prints or logs a secret.

An attachment you ask for is saved to the folder you name, or to your system's temp folder by default.
There is no server of ours, no telemetry and no analytics. The plugin's authors never receive your data.

## What Claude sees

The mail the plugin reads in a session is part of your conversation with Claude, and is handled under
your Claude account's terms and privacy settings.

## How long it keeps it

Until you delete it. Uninstalling the plugin leaves `accounts.json` and your stored app passwords in
place; delete the file and remove the passwords from your credential store to clear them.

## Who it is for

gmail-multi is not intended for anyone under 18.

## Contact

marketplace@crinaro.ai
