/**
 * bot.js
 * Usage: node bot.js <BOT_TOKEN> <CHANNEL_NAME>
 * npm install discord.js @discordjs/voice @discordjs/opus sodium-native
 */

'use strict';

const { Client, GatewayIntentBits } = require('discord.js');
const {
    joinVoiceChannel,
    VoiceConnectionStatus,
    entersState,
    EndBehaviorType,
} = require('@discordjs/voice');
const { OpusEncoder } = require('@discordjs/opus');

const [,, BOT_TOKEN, CHANNEL_NAME] = process.argv;

if (!BOT_TOKEN || !CHANNEL_NAME) {
    process.stderr.write('Usage: node bot.js <BOT_TOKEN> <CHANNEL_NAME>\n');
    process.exit(1);
}

const SAMPLE_RATE = 48000;
const CHANNELS    = 2;

// Write PCM straight to stdout the moment it's decoded — no mixer, no delay
function subscribeUser(receiver, userId) {
    process.stderr.write(`[Audio] ${userId} speaking\n`);

    const encoder = new OpusEncoder(SAMPLE_RATE, CHANNELS);

    const sub = receiver.subscribe(userId, {
        end: { behavior: EndBehaviorType.AfterSilence, duration: 100 },
    });

    sub.on('data', (chunk) => {
        try {
            const pcm = encoder.decode(chunk);
            process.stdout.write(pcm);
        } catch (_) {}
    });

    sub.on('end', () => {
        process.stderr.write(`[Audio] ${userId} stopped\n`);
    });
}

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildVoiceStates,
    ],
});

client.once('ready', async () => {
    process.stderr.write(`[Bot] Logged in as ${client.user.tag}\n`);

    let targetChannel = null;
    for (const guild of client.guilds.cache.values()) {
        const ch = guild.channels.cache.find(
            c => c.name === CHANNEL_NAME && c.isVoiceBased()
        );
        if (ch) { targetChannel = ch; break; }
    }

    if (!targetChannel) {
        await client.guilds.fetch();
        for (const [gid] of client.guilds.cache) {
            const guild = await client.guilds.fetch(gid);
            const ch = guild.channels.cache.find(
                c => c.name === CHANNEL_NAME && c.isVoiceBased()
            );
            if (ch) { targetChannel = ch; break; }
        }
    }

    if (!targetChannel) {
        process.stderr.write(`[Bot] Channel "${CHANNEL_NAME}" not found\n`);
        process.exit(1);
    }

    const connection = joinVoiceChannel({
        channelId:      targetChannel.id,
        guildId:        targetChannel.guild.id,
        adapterCreator: targetChannel.guild.voiceAdapterCreator,
        selfDeaf:       false,
        selfMute:       true,
    });

    try {
        await entersState(connection, VoiceConnectionStatus.Ready, 30_000);
        process.stderr.write(`[Bot] Connected to "${targetChannel.name}"\n`);
        process.stderr.write('[Bot] READY\n');
    } catch (err) {
        process.stderr.write(`[Bot] Failed: ${err.message}\n`);
        connection.destroy();
        process.exit(1);
    }

    connection.receiver.speaking.on('start', (userId) => {
        subscribeUser(connection.receiver, userId);
    });

    connection.on(VoiceConnectionStatus.Disconnected, async () => {
        process.stderr.write('[Bot] Disconnected — reconnecting...\n');
        try {
            await Promise.race([
                entersState(connection, VoiceConnectionStatus.Signalling, 5_000),
                entersState(connection, VoiceConnectionStatus.Connecting, 5_000),
            ]);
        } catch {
            process.stderr.write('[Bot] Reconnect failed\n');
            process.exit(1);
        }
    });
});

process.on('SIGINT',  () => { client.destroy(); process.exit(0); });
process.on('SIGTERM', () => { client.destroy(); process.exit(0); });

client.login(BOT_TOKEN).catch(err => {
    process.stderr.write(`[Bot] Login failed: ${err.message}\n`);
    process.exit(1);
});