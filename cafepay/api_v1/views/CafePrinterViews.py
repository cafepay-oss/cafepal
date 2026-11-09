from rest_framework import generics, serializers

from cafepay.api_v1.consumers.helpers import get_object_or_404
from cafepay.api_v1.helpers import notify_printers
from cafepay.api_v1.permissions import IsStaff
from cafepay.api_v1.serializers.CafePrinterSerializer import PrinterSerializer, PrintRawDataSerializer
from cafepay.models import Cafe, Printer, PrinterJob


class CafePrinterCreateView(generics.CreateAPIView):
    """
    Create a printer for a cafe

    policies:
    ONE_PAGE = "0"
    GROUPED = "1"

    """

    permission_classes = (IsStaff,)

    serializer_class = PrinterSerializer

    def perform_create(self, serializer):
        print("here")
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        serializer.save(cafe=cafe)


class CafePrinterRetrieveUpdateView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve update delete cafe printer

    type guid:
    0: kitchen printer
    1: customer printer
    """

    permission_classes = (IsStaff,)
    serializer_class = PrinterSerializer
    queryset = Printer.objects.all()

    lookup_url_kwarg = 'printer_id'
    lookup_field = 'pk'


class CafePrinterListView(generics.ListAPIView):
    """List of cafe printers"""

    permission_classes = (IsStaff,)
    serializer_class = PrinterSerializer

    def get_queryset(self):
        cafe = get_object_or_404(Cafe, pk=self.kwargs.get('cafe_id'))
        return cafe.printers.all()


class PrintRawDataView(generics.CreateAPIView):
    """Send raw data for print"""

    permission_classes = (IsStaff,)
    serializer_class = PrintRawDataSerializer

    def perform_create(self, serializer):
        printer = get_object_or_404(Printer,
                                    pk=self.kwargs.get('printer_id'))
        serializer.save(printer=printer)
        notify_printers(printer)


class PrinterActiveJobsListView(generics.ListAPIView):
    permission_classes = (IsStaff,)
    serializer_class = PrintRawDataSerializer

    def get_queryset(self):
        printer = get_object_or_404(Printer, pk=self.kwargs.get('printer_id'))
        return printer.jobs.filter(is_done=False)


class PrinterJobRUDView(generics.RetrieveUpdateDestroyAPIView):
    """RUD printer job"""

    permission_classes = (IsStaff, )
    serializer_class = PrintRawDataSerializer

    queryset = PrinterJob.objects.all()
    lookup_field = 'pk'
    lookup_url_kwarg = 'printer_job_id'
