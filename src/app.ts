import { join } from 'path'
import { createBot, createProvider, createFlow, addKeyword, utils, EVENTS } from '@builderbot/bot'
import { MemoryDB as Database } from '@builderbot/bot'
import { BaileysProvider as Provider } from '@builderbot/provider-baileys'
import axios from 'axios';
import FormData from 'form-data';
import fs from 'fs/promises'; // Use fs.promises to handle promise-based filesystem operations
import { createReadStream } from 'fs';  
import { fileURLToPath } from 'url';


const PORT = process.env.PORT ?? 3008

const discordFlow = addKeyword<Provider, Database>('doc').addAnswer(
    ['You can see the documentation here', '📄 https://builderbot.app/docs \n', 'Do you want to continue? *yes*'].join(
        '\n'
    ),
    { capture: true },
    async (ctx, { gotoFlow, flowDynamic }) => {
        if (ctx.body.toLocaleLowerCase().includes('yes')) {
            return gotoFlow(registerFlow)
        }
        await flowDynamic('Thanks!')
        return
    }
)

const welcomeFlow = addKeyword(EVENTS.WELCOME).addAction(
    async (ctx, ctxFn) => {
        try {
            const assistId = "";
            console.log("Mensaje entrante : ", ctx.body);

            // Prepare the data to send to the FastAPI endpoint
            const postData = {
                text: ctx.body
            };

            // Send the data to the FastAPI endpoint
            const response = await axios.post('http://127.0.0.1:8000/process-invoice-text/', postData);

            // Extract the processed response
            const data = response.data.processed_response;
            console.log('Mensaje saliente : ', data);

            // Split the response into chunks and send dynamically
            const chunks = data.split(/(?<!\d)\.\s+/g);
            for (const chunk of chunks) {
                await ctxFn.flowDynamic(chunk);
            }

            console.log("🙉 Envio de mensajes completado....");
        } catch (error) {
            console.error('Error in flowWelcome:', error);
            await ctxFn.flowDynamic("Lo siento, ocurrió un error al procesar tu mensaje.");
        }
    }
);

// Convert `import.meta.url` to a file path
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
import path from 'path';
const dbFilePath = path.join(__dirname, '../db.txt');

const mediaFlow = addKeyword(EVENTS.MEDIA).addAction(
    async (ctx, ctxFn) => {
        try {
            console.log("Media received: ", ctx);
            
            // Save the incoming media file to a local path
            const localPath = await ctxFn.provider.saveFile(ctx, { path: '' });
            console.log("Media saved at: ", localPath);

            const formData = new FormData();
            formData.append('file', createReadStream(localPath));

            const response = await axios.post('http://127.0.0.1:8000/extract-invoice-data/', formData, {
                headers: formData.getHeaders()  // This gets the appropriate headers for boundary
            });

            console.log("API Response: ", response.data);

            // Extract cleaned response
            const cleanedResponse = response.data.cleaned_response;
            const cleanedResponseString = JSON.stringify(cleanedResponse, null, 2);

            // Append the response to the db.txt file
            try {
                await fs.appendFile(dbFilePath, `\n${cleanedResponseString}\n`);
                console.log("Data successfully appended to db.txt");
            } catch (fileError) {
                console.error('Error writing to db.txt:', fileError);
            }

            // Respond based on the extracted data
            const apiResponseMessage = `Extracted Data: ${cleanedResponseString}`;
            await ctxFn.flowDynamic("Gracias por compartir tu factura, la hemos recibido correctamente");

            console.log("✅ Media handling completed....");
        } catch (error) {
            console.error('Error in mediaFlow:', error);
        }
    }
);

const registerFlow = addKeyword<Provider, Database>(utils.setEvent('REGISTER_FLOW'))
    .addAnswer(`What is your name?`, { capture: true }, async (ctx, { state }) => {
        await state.update({ name: ctx.body })
    })
    .addAnswer('What is your age?', { capture: true }, async (ctx, { state }) => {
        await state.update({ age: ctx.body })
    })
    .addAction(async (_, { flowDynamic, state }) => {
        await flowDynamic(`${state.get('name')}, thanks for your information!: Your age: ${state.get('age')}`)
    })

const fullSamplesFlow = addKeyword<Provider, Database>(['samples', utils.setEvent('SAMPLES')])
    .addAnswer(`💪 I'll send you a lot files...`)
    .addAnswer(`Send image from Local`, { media: join(process.cwd(), 'assets', 'sample.png') })
    .addAnswer(`Send video from URL`, {
        media: 'https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExYTJ0ZGdjd2syeXAwMjQ4aWdkcW04OWlqcXI3Ynh1ODkwZ25zZWZ1dCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/LCohAb657pSdHv0Q5h/giphy.mp4',
    })
    .addAnswer(`Send audio from URL`, { media: 'https://cdn.freesound.org/previews/728/728142_11861866-lq.mp3' })
    .addAnswer(`Send file from URL`, {
        media: 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf',
    })

const main = async () => {
    const adapterFlow = createFlow([welcomeFlow, mediaFlow, registerFlow, fullSamplesFlow])
    
    const adapterProvider = createProvider(Provider)
    const adapterDB = new Database()

    const { handleCtx, httpServer } = await createBot({
        flow: adapterFlow,
        provider: adapterProvider,
        database: adapterDB,
    })

    adapterProvider.server.post(
        '/v1/messages',
        handleCtx(async (bot, req, res) => {
            const { number, message, urlMedia } = req.body
            await bot.sendMessage(number, message, { media: urlMedia ?? null })
            return res.end('sended')
        })
    )

    adapterProvider.server.post(
        '/v1/register',
        handleCtx(async (bot, req, res) => {
            const { number, name } = req.body
            await bot.dispatch('REGISTER_FLOW', { from: number, name })
            return res.end('trigger')
        })
    )

    adapterProvider.server.post(
        '/v1/samples',
        handleCtx(async (bot, req, res) => {
            const { number, name } = req.body
            await bot.dispatch('SAMPLES', { from: number, name })
            return res.end('trigger')
        })
    )

    adapterProvider.server.post(
        '/v1/blacklist',
        handleCtx(async (bot, req, res) => {
            const { number, intent } = req.body
            if (intent === 'remove') bot.blacklist.remove(number)
            if (intent === 'add') bot.blacklist.add(number)

            res.writeHead(200, { 'Content-Type': 'application/json' })
            return res.end(JSON.stringify({ status: 'ok', number, intent }))
        })
    )

    httpServer(+PORT)
}

main()
