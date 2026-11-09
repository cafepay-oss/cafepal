from django.conf.urls import url
from django.urls import path
from cafepay.api_v1.views.CardTransferViews import (CardTransferSettingsView,
    CardTransferStartView, CardTransferDetailView, CardTransferReceiptView,
    CardTransferReviewView, CardTransferListView)
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

from cafepay.api_v1.serializers.ContactUsSerializer import ContactUsCreateSerializer
from cafepay.api_v1.views.AddressViews import CityListView, UserProfileAddressCreate, UserProfileAddressRUD, \
    CafeRegionRUDView, CafeRegionCreateView, CafeRegionListView, CityCreateView, CityRUDView, RegionCreateView, \
    RegionCreateRUDView, RegionListView, CafeRegionPriceBulkCreateView
from cafepay.api_v1.views.CafeCharFieldViews import CafeCharFieldView
from cafepay.api_v1.views.CafeCommentViews import CafeCommentCreate, CafeCommentsList, ElementListView, \
    CafeElementScore, CafeAllElementsScore
from cafepay.api_v1.views.CafePrinterViews import CafePrinterCreateView, CafePrinterRetrieveUpdateView, \
    CafePrinterListView, PrintRawDataView, PrinterActiveJobsListView, PrinterJobRUDView
from cafepay.api_v1.views.ContactUsFormView import ContactUsCreateView
from cafepay.api_v1.views.DebugViews import host_view
from cafepay.api_v1.views.DownloadFileViews import DownloadFilesListView
from cafepay.api_v1.views.MenuViews import (MenuCreateView, MenuListView,
                                            MenuRetrieveUpdateDeleteView,
                                            CategoryProductMenuListView, CategoryProductMenuActiveView,
                                            ToggleMenuActivationStatus, MenuAddRemoveProductView,
                                            MenuBulkAddRemoveProductView)
from cafepay.api_v1.views.CategoryViews import CategoryCreateView, CategoryRUDView, GroupListView, \
    CategoryAddRemoveProductView, CategoryBulkAddRemoveProductView, CategoryProductsView, CategorySetOrderView, \
    GroupCreateView, GroupRUDView, CategoryListView, SetIsDeleteToAllView
from cafepay.api_v1.views.PBRPaymentViews import PBRPaymentSessionCreateView, PBRPaymentManualSessionCreateView, \
    PBRRefundView, PBRInvoiceList, PBRPaymentInvoicesView, PBRInternalRefundView, PBRPaymentMethodSetView, \
    JoinRefundView
from cafepay.api_v1.views.PaymentViews import VerifyPayment, MakePayment
from cafepay.api_v1.views.LocalViews import LocalLoginView
from cafepay.api_v1.modules.payment.mock import MockPaymentGateway
from cafepay.api_v1.views.ProductViews import CreateProductImageView, ProductCreateView, MarkImageAsAvatar, \
    ProductRateCommentAddView, ToggleAvailability, ProductRateCommentListView, UpdateProductImageView, ProductRUDView, \
    ProductListView, CafeProductsSetOrderView, CafeProductsList, ProductBulkUpdateView
from cafepay.api_v1.views.PostViews import (CommentCreateView, CommentListView,
                                            CommentRetrieveUpdateDestroyView, LikeListView,
                                            PostCreateView, PostListView,
                                            PostRetrieveUpdateDeleteView, ToggleLikeView)
from cafepay.api_v1.views.RawLogViews import RawLogCreateView, RawLogListView
from cafepay.api_v1.views.ReportViews import GetProductReports, CafeUsersReportsView, NewCustomersReports, OrderReports, \
    SalesReports
from cafepay.api_v1.views.ShopViews import (CafeAddStaffView, CafeCreateRole,
                                            CafeCreateView, CafeListRole, CafeRUDRole,
                                            CafeStaffDetailView, CafeUpdateView,
                                            CafeAuthTokenView, CafeDeactivateStaffView, CafeStaffListView,
                                            CafePendingStaffListView, CafeAuthInfoByTokenView, CafeBasicInfoView,
                                            CafeBasicInfoByUsernameView, CafeAddImageToGalleryView,
                                            CafeImageUpdateView, CafeGallery, MarkCafeImageAsAvatar,
                                            MarkCafeImageAsHeader, AppendPushSubscription, CafeListView)
from cafepay.api_v1.views.UserProfileViews import UserProfileCreateView, UserProfileRUView, UserProfileAuthTokenView, \
    SendCafepayCode, UserProfileSetPasswordView, UserProfileCafePrivateRView, OrderHistoryView, UserProfileWalletView, \
    UserProfileChargeWallet, AdminUserProfileCreateView, UserProfileVerifyView, UserProfileGetOrCreateView, \
    CreateTempTokenView, UseTempTokenView
from cafepay.api_v1.views.TableViews import (MakeTableJoin,
                                             TableSimpleBillView, TableCreateView,
                                             TableRUDView, TableProductManageByToken,
                                             TableSeparate, TableDetailedBillView, TableTransfer, TableStatusView,
                                             ActivateTableTokenSerializer, CafeAllTableTokens, TableTokenCafeInfo,
                                             TableListView, ActivateTableToken, TableSimpleBillStaffView,
                                             TableProductManageByPk, PBRUpdate, CafeTablesHumanReadable,
                                             TableBulkProductManageByToken, TableBulkProductManageById,
                                             ProductPaymentInfoView, TableStatusFilteredView, TableTokenCreateView)
from cafepay.api_v1.views.JoinViews import JoinSimpleRetrieveView, JoinDetailedRetrieveView, SendJoinView, \
    PbrSendToKitchen, PbrAcceptView, PBRStatusView, SetJoinReadyView, JoinUpdateDescriptionView, CancelJoinView, \
    JoinUpdateIncludeFeeView, JoinUpdateUserProfileAddressView
from cafepay.api_v1.views.BIllViews import BillDetailedView, BillSimpleView
from cafepay.api_v1.views.WalletViews import CafeWalletInvoiceListView


schema_view = get_schema_view(
    openapi.Info(
        title="CafePay API",
        default_version='development version',
        description="CafePay API Documentation\n@spsina\n@SadafAsad",
        contact=openapi.Contact(email="snparvizi75@gmail.com"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)


def Error500(request):
    return 1/0


from cafepay.api_v1.views.TableViews import TableProductChangesByToken, TableProductChangesById

urlpatterns = [
    path('cafe/<int:cafe_id>/card-transfer/settings/', CardTransferSettingsView.as_view()),
    path('cafe/<int:cafe_id>/card-transfers/', CardTransferListView.as_view()),
    path('join/<int:join_id>/card-transfer/', CardTransferStartView.as_view()),
    path('card-transfers/<uuid:transfer_uuid>/', CardTransferDetailView.as_view()),
    path('card-transfers/<uuid:transfer_uuid>/receipt/', CardTransferReceiptView.as_view(), name='card_transfer_receipt'),
    path('card-transfers/<uuid:transfer_uuid>/review/', CardTransferReviewView.as_view()),
    path('table/<table_token>/products/change/', TableProductChangesByToken.as_view()),
    path('table/<int:table_id>/products/change/staff/', TableProductChangesById.as_view()),
    path('local/login/', LocalLoginView.as_view(), name='local_login'),

    # cafe
    path('cafe/add/', CafeCreateView.as_view(),
         name="cafe_add"),
    path('cafe/<int:cafe_id>/update/basic/',
         CafeUpdateView.as_view(), name="cafe_update_basic"),
    path('cafe/<int:cafe_id>/basic/info/',
         CafeBasicInfoView.as_view(), name="cafe_basic_info"),
    path('cafe/<int:cafe_id>/gallery/',
         CafeGallery.as_view()),

    path('cafe/list/', CafeListView.as_view()),

    path('cafe/<int:cafe_id>/push-subscription/append/', AppendPushSubscription.as_view()),

    path('cafe/by-username/<str:cafe_username>/basic/info/',
         CafeBasicInfoByUsernameView.as_view(), name="cafe_basic_info_by_username"),

    path('cafe/gallery/image/<int:cafe_image_id>/mark-avatar/', MarkCafeImageAsAvatar.as_view()),
    path('cafe/gallery/image/<int:cafe_image_id>/mark-header/', MarkCafeImageAsHeader.as_view()),

    path('cafe/<int:cafe_id>/gallery/image/add/',
         CafeAddImageToGalleryView.as_view()),

    path('cafe/image/<int:cafe_image_id>/',
         CafeImageUpdateView.as_view()),

    path('cafe/<int:cafe_id>/wallet/invoices/', CafeWalletInvoiceListView.as_view()),

    path('table/<int:table_id>/token/create/', TableTokenCreateView.as_view()),

    path('user-profile/create/as-elevated-user/', AdminUserProfileCreateView.as_view()),
    path('user-profile/temp-token/create/', CreateTempTokenView.as_view()),
    path('user-profile/temp-token/use/', UseTempTokenView.as_view()),

    # todo: add open times , phone numbers

    # cafe staff
    path('cafe/<int:cafe_id>/staff/add/',
         CafeAddStaffView.as_view(), name="cafe_staff_add"),
    path('cafe/<int:cafe_id>/staff/<int:staff_id>/deactivate/',
         CafeDeactivateStaffView.as_view(), name="cafe_staff_deactivate"),
    path('cafe/<int:cafe_id>/staff/<int:staff_id>/',
         CafeStaffDetailView.as_view(), name="cafe_staff_detail"),
    path('cafe/<int:cafe_id>/staff/list/',
         CafeStaffListView.as_view(), name="cafe_staff_list"),
    path('cafe/<int:cafe_id>/pending/staff/list/',
         CafePendingStaffListView.as_view(), name="cafe_pending_staff_list"),
    path('auth/info/',
         CafeAuthInfoByTokenView.as_view(), name="auth_info"),

    # roles
    path('cafe/<int:cafe_id>/role/add/',
         CafeCreateRole.as_view(), name="cafe_add_role"),
    path('cafe/role/<int:role_id>/update/',
         CafeRUDRole.as_view(), name="cafe_role_update"),
    path('cafe/<int:cafe_id>/role/list/',
         CafeListRole.as_view(), name="cafe_list_role"),

    # user profile
    path('user-profile/',
         UserProfileRUView.as_view(), name="user_profile_ru"),
    path('user-profile/add/',
         UserProfileCreateView.as_view(), name="user_profile_create"),
    path('user-profile/send-code/',
         SendCafepayCode.as_view(), name="user_profile_send_code"),
    path('user-profile/auth-token/',
         UserProfileAuthTokenView.as_view(), name="user_profile_auth_token"),
    path('user-profile/set-password/',
         UserProfileSetPasswordView.as_view(), name="user_profile_set_password"),
    path('user-profile/cafe-auth-token/',
         CafeAuthTokenView.as_view(), name="cafe_auth_token"),

    path('cafe/<int:cafe_id>/user-profile/get-or-create/', UserProfileGetOrCreateView.as_view()),

    path('user-profile/<int:user_id>/verify/',
         UserProfileVerifyView.as_view()),
    
    path('user-profile/cafe-private/<uuid:private_id>/',
         UserProfileCafePrivateRView.as_view(), name="user_profile_cafe_private"),

    path('user-profile/orders/history/',
         OrderHistoryView.as_view(), name="user_orders_history"),
    path('user-profile/wallet/', UserProfileWalletView.as_view()),
    path('user-profile/wallet/charge/', UserProfileChargeWallet.as_view() ),

    # cafe product
    path('cafe/<int:cafe_id>/product/add/',
         ProductCreateView.as_view(), name="product_create"),
    path('product/<int:product_id>/',
         ProductRUDView.as_view(), name="product_retrieve_update_delete"),

    path('cafe/<int:cafe_id>/product/bulk/update/', ProductBulkUpdateView.as_view(), name="product_bulk_update"),
    path('product/<int:product_id>/toggle-availability/',
         ToggleAvailability.as_view(), name="toggle-availability"),
    path('cafe/<int:cafe_id>/product/list/',
         ProductListView.as_view(), name="product_list"),
    path('product/<int:product_id>/image/add/',
         CreateProductImageView.as_view(), name="product_add_image"),
    path('product/image/<int:product_image_id>/',
         UpdateProductImageView.as_view(), name="product_image_update"),
    path('product/image/<int:product_image_id>/mark-avatar/',
         MarkImageAsAvatar.as_view(), name="product_image_mark_avatar"),
    path('cafe/<int:cafe_id>/category-based-menu/list/',
         CategoryProductMenuListView.as_view(), name="category_based_menu_list"),
    path('cafe/<int:cafe_id>/category-based-menu/active/',
         CategoryProductMenuActiveView.as_view(), name="category_based_menu_active"),
    path('product/<int:product_id>/comment/add/',
         ProductRateCommentAddView.as_view(), name="product_comment_add"),
    path('product/<int:product_id>/comments/',
         ProductRateCommentListView.as_view(), name="product_comments_list"),
    path('cafe/<int:cafe_id>/products/', CafeProductsList.as_view()),

    path('cafe/<int:cafe_id>/char-field/create/', CafeCharFieldView.as_view()),

    # cafe menu
    path('cafe/<int:cafe_id>/menu/add/',
         MenuCreateView.as_view(), name="menu_add"),
    path('cafe/<int:cafe_id>/menu/list/',
         MenuListView.as_view(), name="menu_list"),
    path('menu/<int:menu_id>/',
         MenuRetrieveUpdateDeleteView.as_view(), name="menu_update"),
    path('menu/<int:menu_id>/toggle/activation/',
         ToggleMenuActivationStatus.as_view(), name="menu_toggle_activation"),
    path('menu/<int:menu_id>/product/add-remove/',
         MenuAddRemoveProductView.as_view(), name="menu_product_add_remove"),
    path('menu/<int:menu_id>/product/bulk/add-remove/',
         MenuBulkAddRemoveProductView.as_view(), name="menu_product_bulk_add_remove"),

    # cafe category
    path('cafe/<int:cafe_id>/category/add/',
         CategoryCreateView.as_view(), name="cafe_category_add"),

    path('cafe/<int:cafe_id>/group/add/',
         GroupCreateView.as_view(), name="cafe_group_add"),

    path('cafe/<int:cafe_id>/category/list/',
         CategoryListView.as_view(), name="cafe_category_list"),

    path('cafe/<int:cafe_id>/group/list/',
         GroupListView.as_view(), name="cafe_group_list"),

    path('category/<int:category_id>/',
         CategoryRUDView.as_view(), name="cafe_category_detail"),

    path('category/<int:category_id>/set-is-delete-to-all/',
         SetIsDeleteToAllView.as_view(), name="cafe_category_set_is_delete_to_all"),


    path('group/<int:group_id>/',
         GroupRUDView.as_view(), name="cafe_group_detail"),

    path('category/<int:category_id>/product/add-remove/',
         CategoryAddRemoveProductView.as_view(), name="category_add_remove_product"),
    path('category/<int:category_id>/product/bulk/add-remove/',
         CategoryBulkAddRemoveProductView.as_view(), name="category_bulk_add_remove_product"),
    path('category/<int:category_id>/products/',
         CategoryProductsView.as_view(), name="category_products"),

    # cafe table
    path('cafe/<int:cafe_id>/table/add/',
         TableCreateView.as_view(), name="table_add"),
    path('table/<int:table_id>/',
         TableRUDView.as_view(), name="table_update_delete"),
    path('cafe/<int:cafe_id>/tables/',
         TableListView.as_view(), name="cafe_tables_list"),

    # table operations  # todo: LIVE
    path('table/<int:table_id>/separate/',
         TableSeparate.as_view(), name="separate_table"),
    path('table/<int:table_id>/join/<int:table_y>/',
         MakeTableJoin.as_view(), name="join_tables"),
    path('table/<int:table_id>/transfer/<int:table_y>/',
         TableTransfer.as_view(), name="transfer_table"),

    # table token
    path('table-token/<table_token>/activate/',
         ActivateTableToken.as_view(), name="table_token_activate"),
    path('table-token/<table_token>/cafe-info/',
         TableTokenCafeInfo.as_view(), name="table_token_cafe_info"),


    path('join/<int:join_id>/cancel/', CancelJoinView.as_view()),

    path('cafe/<int:cafe_id>/table-token/list/',
         CafeAllTableTokens.as_view(), name="cafe_table_token_list"),

    # todo: don't allow to update after payment completed
    path('join/<int:join_id>/set/description/', JoinUpdateDescriptionView.as_view()),
    path('join/<int:join_id>/set/include-delivery-fee/', JoinUpdateIncludeFeeView.as_view()),
    path('join/<int:join_id>/set/user-profile-address/', JoinUpdateUserProfileAddressView.as_view()),

    # cafe post
    path('cafe/<int:cafe_id>/post/add/',
         PostCreateView.as_view(), name="post"),
    path('cafe/<int:cafe_id>/post/list/',
         PostListView.as_view(), name="post_list"),
    path('post/<int:post_id>/',
         PostRetrieveUpdateDeleteView.as_view(), name="post_RUD"),

    # cafe post comments
    path('comment/add/',
         CommentCreateView.as_view(), name="comment_add"),
    path('comment/<int:comment_id>/',
         CommentRetrieveUpdateDestroyView.as_view(), name="comment_delete"),
    path('post/<int:post_id>/comment/list/',
         CommentListView.as_view(), name="comment_list"),

    # cafe post like
    path('post/<int:post_id>/like/',
         ToggleLikeView.as_view(), name="toggle_like"),
    path('post/<int:post_id>/like/list/',
         LikeListView.as_view(), name="like_list"),

    # cafe comment
    path('cafe/comment/create/',
         CafeCommentCreate.as_view(), name="cafe_comment_create"),

    path('cafe/<int:cafe_id>/comment/list/',
         CafeCommentsList.as_view(), name="cafe_comment_list"),

    path('cafe/<int:cafe_id>/el/<int:el_id>/data/',
         CafeElementScore.as_view(), name="cafe_el_data"),

    path('cafe/<int:cafe_id>/el/all/data/',
         CafeAllElementsScore.as_view(), name="cafe_el_add_data"),

    # cafe comment elements
    path('el/list/',
         ElementListView.as_view(), name="el_list"),

    # bill simple/detailed view
    path('bill/detailed/<int:bill_id>/',
         BillDetailedView.as_view(), name="bill_detailed_info"),
    path('bill/simple/<int:bill_id>/',
         BillSimpleView.as_view(), name="bill_simple_info"),

    # join simple/detailed view
    path('join/simple/<int:join_id>/',
         JoinSimpleRetrieveView.as_view(), name="join_simple_info"),
    path('join/detailed/<int:join_id>/',
         JoinDetailedRetrieveView.as_view(), name="join_detailed_info"),

    # join operation
    path('join/send/<int:join_id>/',
         SendJoinView.as_view(), name="join_send"),

    path('pbr/<int:pbr_id>/send-to-kitchen/', PbrSendToKitchen.as_view()),
    path('pbr/<int:pbr_id>/accept/', PbrAcceptView.as_view()),
    path('cafe/<int:cafe_id>/pbr/payment/method/', PBRPaymentMethodSetView.as_view()),

    # cafe tables bill simple
    path('cafe/<int:cafe_id>/tables/join/simple/',
         TableStatusView.as_view(), name="cafe_tables_simple_join"),

    path('cafe/<int:cafe_id>/tables/join/simple/filtered/',
         TableStatusFilteredView.as_view()),

    path('cafe/<int:cafe_id>/products/set/order/', CafeProductsSetOrderView.as_view()),
    path('cafe/<int:cafe_id>/categories/set/order/', CategorySetOrderView.as_view()),

    path('cafe/<int:cafe_id>/products/payment-info/', ProductPaymentInfoView.as_view()),

    path('cafe/<int:cafe_id>/tables/join/simple/human-readable/', CafeTablesHumanReadable.as_view()),

    # path('cafe/<int:cafe_id>/join/simple/history/')

    path('table/<int:table_token>/join/simple/',
         TableSimpleBillView.as_view(), name="table_join_simple"),

    path('table/<int:table_id>/join/simple/staff/',
         TableSimpleBillStaffView.as_view(), name="table_join_simple_staff"),

    path('table/<int:table_id>/bill/detailed/',
         TableDetailedBillView.as_view(), name="table_join_detailed"),

    # bill - product
    path('table/<int:table_token>/product/<int:product_id>/',
         TableProductManageByToken.as_view(), name="product_table"),

    # the code is, cod

    path('table/<table_token>/products/bulk/<method>/', TableBulkProductManageByToken.as_view()),
    path('table/<int:table_id>/products/bulk/<method>/staff/', TableBulkProductManageById.as_view()),

    path('join/<int:join_id>/set/ready-time/', SetJoinReadyView.as_view()),

    path('table/<int:table_id>/product/<int:product_id>/staff/',
         TableProductManageByPk.as_view(), name="product_table_staff"),

    # pbr session payments
    path('pbr/session/create/',
         PBRPaymentSessionCreateView.as_view(), name="pbr_session_create"),

    path('pbr/session/<int:cafe_id>/create/',
         PBRPaymentManualSessionCreateView.as_view(), name="pbr_session_manual_create"),

    path('pbr/<int:pbr_id>/update/',
         PBRUpdate.as_view(), name="pbr_update"),

    path('cafe/<int:cafe_id>/pbr/status/', PBRStatusView.as_view()),

    # path('pbr/<int:cafe_id>/refund/',  # todo: LIVE
    #      PBRRefundView.as_view(), name="pbr_refund"),


    # path('join/<int:join_id>/refund-online-payments/', JoinRefundView.as_view()),
    # path('pbr/<int:cafe_id>/internal/refund/', PBRInternalRefundView.as_view()),

    # pbr invoices by private id
    path('pbr/<uuid:private_id>/invoice/list/',
         PBRInvoiceList.as_view(), name="pbr_invoice_list"),

    path('pbr/<uuid:private_id>/payment/invoice/list/',
         PBRPaymentInvoicesView.as_view(), name="pbr_invoice_list"),

    path('payment/make/<invoice_uuid>/', MakePayment.as_view()),
    path('payment/mock/<uuid:invoice_uuid>/', MockPaymentGateway.as_view(), name='mock_payment'),

    path('verify/<invoice_uuid>/<pg>/',
         VerifyPayment.as_view(), name="payment_verify"),

    # report APIs
    path('cafe/<int:cafe_id>/products/report/',
         GetProductReports.as_view()),
    path('cafe/<int:cafe_id>/users/reports/', CafeUsersReportsView.as_view()),

    # cafe printers
    path('cafe/<int:cafe_id>/printer/add/', CafePrinterCreateView.as_view()),
    path('printer/<int:printer_id>/', CafePrinterRetrieveUpdateView.as_view()),
    path('cafe/<int:cafe_id>/printers/list/', CafePrinterListView.as_view()),

    path('printer/<int:printer_id>/job/create/', PrintRawDataView.as_view()),
    path('printer/<int:printer_id>/jobs/list/', PrinterActiveJobsListView.as_view()),
    path('printer-job/<int:printer_job_id>/', PrinterJobRUDView.as_view()),

    path('downloads/list/', DownloadFilesListView.as_view()),
    path('contact-us/create/', ContactUsCreateView.as_view()),

    path('host/', host_view),

    # managerial reports
    path('cafe/<int:cafe_id>/report/new-customers/', NewCustomersReports.as_view()),
    path('cafe/<int:cafe_id>/report/orders/', OrderReports.as_view()),
    path('cafe/<int:cafe_id>/report/sales/', SalesReports.as_view()),


    path('city/create/', CityCreateView.as_view()),
    path('city/<int:city_id>/', CityRUDView.as_view()),
    path('city/<int:city_id>/regions/', RegionListView.as_view()),
    path('city/list/', CityListView.as_view()),

    path('region/create/', RegionCreateView.as_view()),
    path('region/<int:region_id>/', RegionCreateRUDView.as_view()),


    path('user-profile/address/create/', UserProfileAddressCreate.as_view()),
    path('user-profile/address/<int:address_id>/', UserProfileAddressRUD.as_view()),

    path('cafe/<int:cafe_id>/region-price/create/', CafeRegionCreateView.as_view()),
    path('cafe/<int:cafe_id>/region-price/bulk/create/', CafeRegionPriceBulkCreateView.as_view()),
    path('region-price/<int:region_price_id>/', CafeRegionRUDView.as_view()),
    path('cafe/<int:cafe_id>/region-price/list/', CafeRegionListView.as_view()),

    path('error500/', Error500),

    path('raw-log/create/', RawLogCreateView.as_view()),
    path('raw-log/list/', RawLogListView.as_view()),

    # docs
    url(r'^swagger(?P<format>\.json|\.yaml)$', schema_view.without_ui(cache_timeout=0), name='schema-json'),
    url(r'^swagger/$', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    url(r'^redoc/$', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
]
