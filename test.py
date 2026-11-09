from cafepay.models import *
c = Cafe.objects.first()
t1 = c.shop_tables.all()[0]
t2 = c.shop_tables.all()[1]
p = c.products.all()
t1.make_join(t2)
t1.add_product(p[0])
t1.separate()