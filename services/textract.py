import boto3
import json
import logging
from pdf2image import convert_from_bytes
import io
from botocore.exceptions import ClientError
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

#requiere instalar poppler en el sistema para convertir a imagen el pdf.

#SDK para Python (Boto3) https://docs.aws.amazon.com/es_es/textract/latest/dg/example_textract_DetectDocumentText_section.html
#Detección de texto síncrono
class TextractWrapper_Sincrono:
    """Encapsulates Textract functions."""
    def __init__(self, textract_client, s3_resource, sqs_resource):
        """
        :param textract_client: A Boto3 Textract client.
        :param s3_resource: A Boto3 Amazon S3 resource.
        :param sqs_resource: A Boto3 Amazon SQS resource.
        """
        self.textract_client = textract_client
        self.s3_resource = s3_resource
        self.sqs_resource = sqs_resource

    def detect_file_text(self, *, document_file_name=None, document_bytes=None):
        """
        Detects text elements in a local image file or from in-memory byte data.
        The image must be in PNG or JPG format.

        :param document_file_name: The name of a document image file.
        :param document_bytes: In-memory byte data of a document image.
        :return: The response from Amazon Textract, including a list of blocks
                 that describe elements detected in the image.
        """
        if document_file_name is not None:
            with open(document_file_name, 'rb') as document_file:
                document_bytes = document_file.read()
        try:
            response = self.textract_client.detect_document_text(
                Document={'Bytes': document_bytes})
            logger.info(
                "Detected %s blocks.", len(response['Blocks']))
        except ClientError:
            logger.exception("Couldn't detect text.")
            raise
        else:
            return response
        
    def process_text_analysis(self, *, document_file_name=None, document_bytes=None):
        if document_file_name is not None:
            with open(document_file_name, 'rb') as document_file:
                document_bytes = document_file.read()
        try:
            response = self.textract_client.analyze_document(
                Document={'Bytes': document_bytes},
                FeatureTypes=["TABLES"])
            logger.info(
                "Detected %s blocks.", len(response['Blocks']))
            
            blocks=response['Blocks']
            # print(blocks)

            blocks_map = {}
            table_blocks = []
            for block in blocks:
                blocks_map[block['Id']] = block
                if block['BlockType'] == "TABLE":
                    table_blocks.append(block)

            if len(table_blocks) <= 0:
                return "<b> NO Table FOUND </b>"

            csv = ''
            for index, table in enumerate(table_blocks):
                csv += self.generate_table_csv(table, blocks_map, index +1)
                csv += '\n\n'

        except ClientError:
            logger.exception("Couldn't detect text.")
            raise
        else:
            return csv

    def generate_table_csv(self,table_result, blocks_map, table_index):
        rows, scores = self.get_rows_columns_map(table_result, blocks_map)
        table_id = 'Table_' + str(table_index)
        csv = ''

        for row_index, cols in rows.items():
            for col_index, text in cols.items():
                col_indices = len(cols.items())
                csv += '{}'.format(text) + ";"
            csv += '\n'

        return csv
    
    def get_rows_columns_map(self,table_result, blocks_map):
        rows = {}
        scores = []
        for relationship in table_result['Relationships']:
            if relationship['Type'] == 'CHILD':
                for child_id in relationship['Ids']:
                    cell = blocks_map[child_id]
                    if cell['BlockType'] == 'CELL':
                        row_index = cell['RowIndex']
                        col_index = cell['ColumnIndex']
                        if row_index not in rows:
                            # create new row
                            rows[row_index] = {}
                        
                        # get confidence score
                        scores.append(str(cell['Confidence']))
                            
                        # get the text value
                        rows[row_index][col_index] = self.get_text(cell, blocks_map)
                        
        return rows, scores

    def get_text(self,result, blocks_map):
        text = ''
        if 'Relationships' in result:
            for relationship in result['Relationships']:
                if relationship['Type'] == 'CHILD':
                    for child_id in relationship['Ids']:
                        word = blocks_map[child_id]
                        if word['BlockType'] == 'WORD':
                            if "," in word['Text'] and word['Text'].replace(",", "").isnumeric():
                                text += '"' + word['Text'] + '"' + ' '
                            else:
                                text += word['Text'] + ' '
                        if word['BlockType'] == 'SELECTION_ELEMENT':
                            if word['SelectionStatus'] =='SELECTED':
                                text +=  'X '
        return text

    def detect_invoice_data(self, *, document_file_name=None, document_bytes=None):
        if document_file_name is not None:
            with open(document_file_name, 'rb') as document_file:
                document_bytes = document_file.read()
        try:
            # Check if the file is already in image format
            image_bytes = io.BytesIO(document_bytes)
            
            # Optionally convert PDF to images if needed, you can comment this out for JPEG
            # images = convert_from_bytes(document_bytes, fmt='png')

            # For PDF files:
            # if len(images) > 0:
            #     first_page = images[0]
            #     image_bytes = io.BytesIO()
            #     first_page.save(image_bytes, format='PNG')
            #     image_bytes.seek(0)

            response = self.textract_client.analyze_expense(
                Document={'Bytes': image_bytes.read()}
            )
            new_response = self.remove_geometries(response)
        except ClientError:
            logger.exception("Couldn't detect text.")
            raise
        else:
            return response, new_response
        
    def print_labels_and_values(field):
        # Only if labels are detected and returned
        if "LabelDetection" in field:
            print("Summary Label Detection - Confidence: {}".format(
                str(field.get("LabelDetection")["Confidence"])) + ", "
                + "Summary Values: {}".format(str(field.get("LabelDetection")["Text"])))
            print(field.get("LabelDetection")["Geometry"])
        else:
            print("Label Detection - No labels returned.")
        if "ValueDetection" in field:
            print("Summary Value Detection - Confidence: {}".format(
                str(field.get("ValueDetection")["Confidence"])) + ", "
                + "Summary Values: {}".format(str(field.get("ValueDetection")["Text"])))
            print(field.get("ValueDetection")["Geometry"])
        else:
            print("Value Detection - No values returned")

    def imprimir_texto_imagen(self, file_path):
        try:
            response = self.detect_file_text(document_file_name=file_path)
        except ClientError as e:
            print(f"Error: {e}")
            return

        texto_con_coordenadas = []
        for item in response["Blocks"]:
            if item["BlockType"] == "LINE":
                texto = item["Text"]
                print(f"texto: {texto}")
                coordenadas = item["Geometry"]["BoundingBox"]
                left = coordenadas["Left"]
                top = coordenadas["Top"]
                width = coordenadas["Width"]
                height = coordenadas["Height"]
                print(f"left: {left}")
                print(f"top: {top}")
                print(f"width: {left}")
                print(f"height: {left}")
                # Obtener las dimensiones de la imagen
                image_width = 1920
                image_height = 1080

                # Calcular las coordenadas en píxeles
                x1 = int(left * image_width)
                y1 = int(top * image_height)
                x2 = int((left + width) * image_width)
                y2 = int((top + height) * image_height)

                texto_con_coordenadas.append((texto, (x1, y1, x2, y2)))

        return texto_con_coordenadas
    
    def compare_text(self, file_path):
        try:
            response = self.detect_file_text(document_file_name=file_path)
            print(response)
        except ClientError as e:
            print(f"Error: {e}")
            return

        texto_con_coordenadas = []
        for item in response["Blocks"]:
            if item["BlockType"] == "LINE":
                texto = item["Text"]
                # print(f"texto: {texto}")
                return texto
        return 'None'

    def remove_geometries(self,obj):
        if isinstance(obj, dict):
            # Si el objeto es un diccionario, recorrer sus claves y valores
            new_obj = {}
            for key, value in obj.items():
                if key != 'Geometry':
                    new_obj[key] = self.remove_geometries(value)
            return new_obj
        elif isinstance(obj, list):
            # Si el objeto es una lista, recorrer sus elementos
            return [self.remove_geometries(item) for item in obj]
        else:
            # Si el objeto no es un diccionario ni una lista, devolverlo sin cambios
            return obj
