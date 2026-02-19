# X/Twitter Integration Guide

Your Fantastic Claw agent is now integrated with X (Twitter)! Here's how to set it up.

## Step 1: Create a Twitter Bot Account

1. Go to [twitter.com](https://twitter.com) and create a new account
2. Name it something like `@FantasticClaw` or `@TheClaw`
3. Set an avatar and bio

## Step 2: Apply for X API Access

1. Go to [developer.twitter.com](https://developer.twitter.com)
2. Sign in with your bot account
3. Click **"Create an app"** or go to **Dashboard → Projects & Apps**
4. Fill in the app details:
   - **App name**: The Fantastic Claw
   - **Use case**: Bot for product analysis
   - **Description**: An AI agent that analyzes product listings for flipping potential

5. Accept terms and create the app

## Step 3: Get Your API Credentials

1. Go to your app's **Keys and tokens** page
2. Copy these credentials:
   - **API Key** (Consumer Key)
   - **API Secret** (Consumer Secret)
   - **Bearer Token**
   - **Access Token**
   - **Access Token Secret**

3. Add them to your `.env` file:

```
TWITTER_CONSUMER_KEY=your_consumer_key
TWITTER_CONSUMER_SECRET=your_consumer_secret
TWITTER_ACCESS_TOKEN=your_access_token
TWITTER_ACCESS_TOKEN_SECRET=your_access_token_secret
TWITTER_BEARER_TOKEN=your_bearer_token
BOT_TWITTER_HANDLE=YourBotHandle
```

## Step 4: Enable v2 API and Restricted Endpoints

1. In **Keys and tokens → Settings** (scroll down)
2. Change **API access level** to: **Elevated**
3. Enable these **OAuth 2.0 Settings**:
   - Read write - Allow your app to make POST requests
   - Tweet.read scope - Allow reading tweets
   - Users.read scope - Allow reading users info

## Step 5: Set Up the Webhook

Your Render deployment URL is where Twitter will send mentions.

1. Go to **Keys and tokens → Webhooks and connections**
2. Click **Add webhook**
3. Enter your webhook URL:
   ```
   https://your-render-app-name.onrender.com/twitter-webhook
   ```

4. Twitter will send a verification request - your app will auto-respond with the correct token

5. In **Environments → Dev environment**, select your webhook

## Step 6: Subscribe to User Events

1. In **Webhooks and connections**, go to **Account Activity API**
2. Click **Subscribe** to receive mentions

## Step 7: Test It!

Now when someone tweets at your bot, it will respond:

```
@FantasticClaw https://www.example.com/vintage-chair

# Bot responds with:
@User This vintage chair at $45 is 40% below market value. Great flip! 🦀
```

## How It Works

1. **User tweets**: `@FantasticClaw https://example.com/product`
2. **Twitter sends**: POST request to `/twitter-webhook`
3. **Your agent**:
   - Extracts the URL
   - Scrapes the product
   - Analyzes with GPT-4o
   - Replies with analysis
4. **Bot tweets back**: Witty evaluation of the deal

## Endpoints

### Manual Trigger
```bash
POST /trigger-claw?url=https://example.com/product
```

### Health Check
```bash
GET /
```

### Twitter Webhook (Automatic)
```
POST /twitter-webhook
GET /twitter-webhook?crc_token=...
```

## Troubleshooting

### Bot not receiving mentions
- ✓ Check webhook URL is correct and publicly accessible
- ✓ Verify API credentials in `.env`
- ✓ Make sure you're using **Elevated** API access level
- ✓ Check Render logs: `Render dashboard → Logs`

### Webhook verification failing
- Render needs to respond within 3 seconds
- Check that your app is running and responding to GET `/twitter-webhook`

### Rate limiting
- Twitter has rate limits (450 tweets/15 minutes)
- The code includes `wait_on_rate_limit=True` to handle this

### Check Logs
```bash
# On Render dashboard, view real-time logs
Render → Your App → Logs
```

Look for messages like:
```
New mention: @FantasticClaw https://example.com/product
Replied to tweet 1234567890
```

## Advanced: Custom Analysis

To change how the bot analyzes products, edit the system prompt in `agent.py`:

```python
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are The Fantastic Claw. [Your custom instructions here]"),
    ...
])
```

## API Limits

- **Tweet read**: 450 tweets/15 minutes
- **Tweet creation**: 300 tweets/15 minutes
- **User lookup**: 15 requests/15 minutes

The code automatically handles rate limiting with `wait_on_rate_limit=True`.

## Security Notes

- ✅ **Never commit `.env`** - it's in `.gitignore`
- ✅ **Keep API keys private** - never share them
- ✅ **Rotate tokens regularly** in Twitter dashboard
- ✅ **Monitor usage** - Watch your API call count

## Next Steps

1. Add your X API credentials to `.env`
2. Restart your Render app
3. Tweet at your bot with a product link
4. Watch it respond! 🦀

## Support

For issues:
- Check Twitter API status: [status.twitter.com](https://status.twitter.com)
- View Render logs: Your app dashboard
- Twitter Dev docs: [developer.twitter.com/docs](https://developer.twitter.com/docs)
